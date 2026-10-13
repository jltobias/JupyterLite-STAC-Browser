"""Offline regressions for audit evidence and bounded provider probes."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import live_catalog_check as audit


class AuditTests(unittest.TestCase):
    def test_run_directories_are_unique_and_document_omitted_checks_and_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'web').mkdir()
            (root / 'web/app.js').write_text('fixture source')
            with patch.object(audit.subprocess, 'check_output', side_effect=['abc123', ' M web/app.js'] * 2):
                first, one = audit.run_manifest(root / 'runs', True, ['presets'], root)
                (first / 'assets.json').write_text('old optional result')
                second, two = audit.run_manifest(root / 'runs', False, ['presets', 'assets'], root)
            self.assertNotEqual(first, second)
            self.assertFalse((second / 'assets.json').exists())
            self.assertEqual(one['status'], 'incomplete')
            self.assertEqual(one['mode'], 'source')
            self.assertEqual(two['mode'], 'deployed')
            self.assertEqual(one['omitted_checks'], ['directory_ui', 'assets', 'directory'])
            self.assertEqual(two['enabled_checks'], ['presets', 'assets'])
            self.assertEqual(one['git_revision'], 'abc123')
            self.assertTrue(one['git_dirty'])
            self.assertEqual(one['source_sha256']['web/app.js'], hashlib.sha256(b'fixture source').hexdigest())

    def test_source_route_has_no_deployed_fallback_for_missing_or_escaped_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'index.html').write_text('local app')
            for path, local in [('', True), ('missing.js', False), ('../outside.js', False), ('%2e%2e/outside.js', False)]:
                route = SimpleNamespace(request=SimpleNamespace(url='https://fixture.test/explorer/' + path), fulfill=Mock(), continue_=Mock())
                audit.source_route(route, 'https://fixture.test/explorer/', root)
                if local:
                    self.assertEqual(route.fulfill.call_args.kwargs, {'path': root / 'index.html'})
                else:
                    self.assertEqual(route.fulfill.call_args.kwargs['status'], 404)
                route.continue_.assert_not_called()

    def test_harness_failure_preserves_partial_results_and_incomplete_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            def fail(page, out):
                audit.write_json(out / 'presets.json', [{'preset': 'fixture', 'outcome': 'passed'}])
                raise RuntimeError('fixture harness failure https://private.test/?token=secret')
            with patch.object(audit, 'sync_playwright') as runtime, patch.object(audit, 'expect'), \
                    patch.object(audit, 'presets', side_effect=fail), \
                    patch.object(sys, 'argv', ['live_catalog_check.py', '--source', '--output', temp]):
                runtime.return_value.__enter__.return_value.chromium.launch.return_value.version = 'fixture-browser-1'
                self.assertEqual(audit.main(), 1)
            run = next(output.iterdir())
            manifest = json.loads((run / 'audit.json').read_text())
            self.assertEqual(manifest['status'], 'incomplete')
            self.assertEqual(manifest['phase'], 'presets')
            self.assertEqual(manifest['browser_version'], 'fixture-browser-1')
            self.assertEqual(manifest['origin'], {'scheme': 'https', 'host': 'jltobias.github.io', 'port': 443})
            self.assertEqual(manifest['explorer_path'], '/JupyterLite-STAC-Browser/explorer/')
            self.assertEqual(json.loads((run / 'presets.json').read_text())[0]['outcome'], 'passed')
            self.assertNotIn('secret', (run / 'audit.json').read_text())
            self.assertNotIn('private.test', (run / 'audit.json').read_text())

    def test_actual_collection_dates_and_4d_6d_spatial_extents(self):
        collection = {'extent': {'temporal': {'interval': [['2012-04-05T00:00:00+02:00', None], ['2020-01-01T00:00:00Z', None]]},
                                 'spatial': {'bbox': [[30, -1, 5, 33, 3, 10], [31, 0, 32, 1]]}}}
        self.assertEqual(audit.collection_expectations(collection), {'from': '2012-04-04', 'bbox': [30, -1, 33, 3], 'extent': 'usable'})
        for intervals in [None, [], [[None, None]], [['2023-02-29T00:00:00Z', None]], [['2001-01-01', None]]]:
            collection['extent']['temporal']['interval'] = intervals
            self.assertEqual(audit.collection_expectations(collection)['from'], '2000-01-01')
        for bbox, state in [([170, -10, -170, 10], 'crossing antimeridian'), ([30, 0, 30, 0], 'point or line'),
                            ([30, -1, 33, 3], 'usable'), ([30, -1, 11, 33, 3, 10], 'absent or invalid'), (None, 'absent or invalid')]:
            collection['extent']['spatial']['bbox'] = [bbox]
            self.assertEqual(audit.collection_expectations(collection)['extent'], state)
        self.assertEqual(audit.collection_expectations({})['extent'], 'absent or invalid')

    def test_portable_asset_primary_and_https_alternate_order(self):
        primary, preferred, other = 'http://fixture.test/primary.tif', 'https://fixture.test/preferred.tif', 'https://fixture.test/other.tif'
        asset = {'href': primary, 'alternate': {'other': {'href': other}, 'https': {'href': preferred}}}
        self.assertEqual(audit.asset_address(asset), primary)
        asset['href'] = 's3://fixture/source.tif'
        self.assertEqual(audit.asset_address(asset), preferred)
        asset['alternate']['https']['href'] = 'https://user:secret@fixture.test/private.tif'
        self.assertEqual(audit.asset_address(asset), other)
        for value in [None, {}, {'href': './unresolved.tif'}, {'href': 's3://bucket/file', 'alternate': {'https': {'href': 'http://fixture.test/file'}}},
                      {'href': 's3://bucket/file', 'alternate': {'https': None, 'broken': 'bad', 'blank': {'href': ' '}}}]:
            self.assertIsNone(audit.asset_address(value))

    def test_missing_crop_bbox_is_unverified_and_six_dimensions_are_normalized(self):
        for value in [None, [], [0, 0, 0, 1], [170, -1, -170, 1], [0, 0, float('nan'), 1], [False, 0, 1, 1]]:
            self.assertIsNone(audit.tiny_crop_bbox({'bbox': value}))
        self.assertEqual(audit.tiny_crop_bbox({'bbox': [30, -1, 5, 33, 3, 10]}), [31.4995, .9995, 31.5005, 1.0005])
        with tempfile.TemporaryDirectory() as temp:
            page = Mock()
            page.evaluate.return_value = {'status': 206, 'bytes': 16}
            results = audit.assets(page, {'earthsearch': {'assets': {'red': {'href': 'https://fixture.test/red.tif'}}}}, Path(temp))
            self.assertEqual(page.evaluate.call_count, 1)
            self.assertTrue(any('unverified' in rec.get('earthsearch_crop', {}).get('outcome', '') for rec in results))
            self.assertEqual(results[-1]['provider'], 'copernicus')
            self.assertNotIn('https://', (Path(temp) / 'assets.json').read_text())

    def test_pagination_checks_completed_request_history_not_item_count_growth(self):
        first = {'url': 'https://fixture.test/search', 'method': 'POST', 'body': {'limit': 1}}
        page = {'url': 'https://fixture.test/redirect/search', 'data': {'links': [
            {'rel': 'next', 'href': '/html', 'type': 'text/html'},
            {'rel': 'next', 'href': './next', 'type': 'application/geo+json', 'method': 'POST', 'merge': True, 'body': {'cursor': 2}}]}}
        expected = audit.expected_next(page, first)
        self.assertEqual(expected, {'url': 'https://fixture.test/redirect/next', 'method': 'POST', 'body': {'limit': 1, 'cursor': 2}})
        before = {'count': 1, 'requests': [first]}
        self.assertTrue(audit.pagination_matches(before, {'count': 1, 'requests': [first, expected]}, expected))
        for after, advertised in [(before, expected), ({'count': 2, 'requests': [first, first]}, expected),
                                  ({'count': 2, 'requests': [first, first]}, first)]:
            self.assertFalse(audit.pagination_matches(before, after, advertised))

    def test_completed_polygon_and_no_filter_queries_match_submitted_geometry(self):
        polygon = {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
        good = {'spatial_mode': 'polygon', 'query': {'limit': 1, 'intersects': polygon}}
        self.assertTrue(audit.spatial_query_matches(good, 'polygon', polygon))
        wrong = copy.deepcopy(good)
        wrong['query']['intersects']['coordinates'][0][1][0] = 2
        self.assertFalse(audit.spatial_query_matches(wrong, 'polygon', polygon))
        self.assertTrue(audit.spatial_query_matches({'spatial_mode': 'none', 'query': {'limit': 1}}, 'none'))
        for key in ['bbox', 'intersects']:
            self.assertFalse(audit.spatial_query_matches({'spatial_mode': 'none', 'query': {key: None}}, 'none'))

    def test_static_depth_boundary_inspects_fourth_child_without_fetching_a_fifth(self):
        node = audit.ROOT / '.tools/node-v22.17.0-win-x64/node.exe'
        node = str(node) if node.exists() else shutil.which('node')
        if not node:
            self.skipTest('Node is needed to execute the browser audit traversal helper')
        script = "import assert from 'node:assert/strict';\nconst probe=" + audit.STATIC_PROBE_JS + ";\n" + """
        for (const terminal of ['item', 'child', 'none']) {
            let traversals=0, inspected=[], opened=false;
            const client={url:'https://fixture.test/0', searchLink:null,
                catalogLinks() {inspected.push(traversals);return traversals<4 || terminal==='child'
                    ? [{rel:'child',href:'/'+(traversals+1)}] : terminal==='item' ? [{rel:'item',href:'/item'}] : [];},
                async connect(url) {this.url=url;traversals++;}, async openItem() {opened=true;}};
            const rec={};await probe(client,rec);
            assert.equal(traversals,4);assert.deepEqual(inspected,[0,1,2,3,4]);assert.equal(rec.traversal_depth,4);
            assert.equal(opened,terminal==='item');
            assert.equal(rec.outcome,terminal==='item'?'static item passed':terminal==='child'?'connected; depth cap':'static navigation only');
        }
        """
        subprocess.run([node, '--input-type=module'], input=script, text=True, check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
