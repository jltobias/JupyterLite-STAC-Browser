"""Deterministic featured presets, mixed-media APIs, and nested static navigation."""
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect


def check_catalog_compatibility(page, catalog, items):
    def fulfill(route, data):
        route.fulfill(body=json.dumps(data), content_type='application/json', headers={'Access-Control-Allow-Origin': '*'})

    def export(selector='#export-geojson'):
        with page.expect_download() as downloaded:
            page.locator(selector).click()
        return json.loads(Path(downloaded.value.path()).read_text())

    # Exercise the actual menu mappings with different provider-shaped fixtures.
    cases = [
        ('earthsearch', 'https://earth-search.aws.element84.com/v1', 'sentinel-2-l2a', 'Earth Search fixture',
         {'href': 's3://earth-search-fixture/red.tif', 'type': 'image/tiff', 'alternate': {'https': {'href': 'https://earth-search-assets.test/red.tif'}}}),
        ('planetary', 'https://planetarycomputer.microsoft.com/api/stac/v1', 'landsat-c2-l2', 'Planetary fixture',
         {'href': 'https://planetary-assets.test/red.tif', 'type': 'image/tiff', 'auth:refs': ['sas']}),
    ]
    for preset, endpoint, collection, title, asset in cases:
        calls = []
        item = copy.deepcopy(items['features'][0])
        item.update(id=preset + '-item', collection=collection, assets={'red': asset},
                    links=[{'rel': 'self', 'href': endpoint + '/collections/' + collection + '/items/one'}])
        item['properties'].update(title=title, datetime='2024-06-01T00:00:00Z')

        def fixture(route):
            req = route.request
            calls.append(req.url)
            assert 'authorization' not in req.headers
            if req.url == endpoint:
                data = {**catalog, 'links': [{'rel': 'data', 'href': endpoint + '/collections', 'type': 'application/json'},
                                           {'rel': 'search', 'href': endpoint + '/search', 'type': 'application/geo+json'}]}
            elif req.url == endpoint + '/collections':
                data = {'collections': [{'id': collection, 'title': title, 'extent': {'spatial': {'bbox': [[0, 0, 1, 1]]}}}], 'links': []}
            elif req.url.startswith(endpoint + '/search?'):
                assert parse_qs(urlsplit(req.url).query)['collections'] == [collection]
                data = {'type': 'FeatureCollection', 'features': [item], 'links': []}
            else:
                raise AssertionError('Unexpected preset request: ' + req.url)
            fulfill(route, data)

        pattern = endpoint + '**'
        page.route(pattern, fixture)
        page.locator('#preset').select_option(preset)
        expect(page.locator('#endpoint')).to_have_value(endpoint)
        assert calls == [], 'Choosing a provider must wait for Connect'
        page.locator('#connect').click()
        expect(page.locator('#collection option')).to_have_count(2)
        assert calls == [endpoint, endpoint + '/collections']
        page.locator('#collection').select_option(collection)
        page.locator('#collection-area').click()
        page.locator('#spatial-mode').select_option('bbox')
        page.locator('#search').click()
        expect(page.locator('.result-card')).to_have_count(1)
        page.locator('.result-card').click()
        expect(page.locator('#metadata h3').first).to_have_text(title)
        expect(page.locator('.asset-clip')).to_have_count(1 if preset == 'earthsearch' else 0)
        if preset == 'planetary':
            expect(page.locator('.dataset-downloads')).to_contain_text('Provider authentication required')
        assert export()['features'][0]['assets'] == item['assets']
        assert len(calls) == 3, 'Metadata selection/export must not fetch source assets'
        page.unroute(pattern, fixture)

    host = 'https://catalog-compatibility.test'
    calls = []
    static_item = copy.deepcopy(items['features'][0])
    static_item.update(id='nested-static', collection='nested-collection',
                       links=[{'rel': 'self', 'href': './one.json'}], assets={'data': {'href': '../data/file.tif'}})

    def fixture(route):
        req = route.request
        path = urlsplit(req.url).path
        calls.append((path, req.method))
        if path == '/mixed':
            data = {**catalog, 'links': [
                {'rel': 'data', 'href': '/html', 'type': 'text/html'},
                {'rel': 'data', 'href': '/collections', 'type': 'application/json'},
                {'rel': 'search', 'href': '/xml', 'type': 'application/opensearchdescription+xml'},
                {'rel': 'search', 'href': '/xml', 'method': 'POST', 'type': 'application/xml'},
                {'rel': 'search', 'href': '/search', 'type': 'application/geo+json'},
                {'rel': 'search', 'href': '/polygon', 'method': 'POST', 'type': 'application/geo+json'}]}
        elif path == '/collections':
            data = {'collections': [{'id': 'JSON'}]}
        elif path in ('/search', '/polygon'):
            assert req.method == ('POST' if path == '/polygon' else 'GET')
            if path == '/polygon':
                assert json.loads(req.post_data)['intersects']['type'] == 'Polygon'
            data = {'type': 'FeatureCollection', 'features': [static_item], 'links': []}
        elif path == '/unsupported':
            data = {**catalog, 'links': [{'rel': 'data', 'href': '/html', 'type': 'text/html'},
                                       {'rel': 'search', 'href': '/xml', 'type': 'application/xml'}]}
        elif path == '/catalog/root.json':
            data = {**catalog, 'id': 'nested-root', 'title': 'nested-root', 'links': [{'rel': 'child', 'href': './branch/catalog.json', 'title': 'Branch'}]}
        elif path == '/catalog/branch/catalog.json':
            data = {**catalog, 'id': 'nested-branch', 'title': 'nested-branch', 'links': [
                {'rel': 'child', 'href': './deep/collection.json', 'title': 'Collection'},
                {'rel': 'parent', 'href': '../root.json', 'title': 'Parent'},
                {'rel': 'root', 'href': '../root.json', 'title': 'Root'}]}
        elif path == '/catalog/branch/deep/collection.json':
            data = {**catalog, 'type': 'Collection', 'id': 'nested-collection', 'title': 'nested-collection', 'links': [
                {'rel': 'item', 'href': './items/one.json', 'title': 'Nested item'},
                {'rel': 'parent', 'href': '../catalog.json', 'title': 'Parent'},
                {'rel': 'root', 'href': '../../root.json', 'title': 'Root'}]}
        elif path == '/catalog/branch/deep/items/one.json':
            data = static_item
        else:
            raise AssertionError('Unsupported representation or unexpected navigation: ' + req.url)
        fulfill(route, data)

    page.route(host + '/**', fixture)
    page.locator('#preset').select_option('custom')
    page.locator('#endpoint').fill(host + '/mixed')
    page.locator('#connect').click()
    expect(page.locator('#search')).to_be_enabled()
    page.locator('#bbox').fill('0,0,1,1')
    page.locator('#bbox').press('Tab')
    page.locator('#search').click()
    expect(page.locator('.result-card')).to_have_count(1)
    page.locator('#spatial-mode').select_option('polygon')
    page.locator('#search').click()
    expect(page.locator('#search')).to_be_enabled()
    assert calls == [('/mixed', 'GET'), ('/collections', 'GET'), ('/search', 'GET'), ('/polygon', 'POST')]
    page.locator('#endpoint').fill(host + '/unsupported')
    page.locator('#connect').click()
    expect(page.locator('#status')).to_contain_text('Static catalog connected')
    expect(page.locator('#search')).to_be_disabled()
    assert calls[-1] == ('/unsupported', 'GET')

    page.locator('#endpoint').fill(host + '/catalog/root.json')
    page.locator('#connect').click()
    expect(page.locator('#catalog-summary')).to_contain_text('nested-root')
    for label, expected in [('child · Branch', 'nested-branch'), ('parent · Parent', 'nested-root'),
                            ('child · Branch', 'nested-branch'), ('child · Collection', 'nested-collection')]:
        page.get_by_role('button', name=label, exact=True).click()
        expect(page.locator('#catalog-summary')).to_contain_text(expected)
        expect(page.locator('#search')).to_be_disabled()
    page.get_by_role('button', name='item · Nested item', exact=True).click()
    expect(page.locator('#metadata')).to_contain_text('nested-static')
    expect(page.locator('.asset-download')).to_have_attribute('href', host + '/catalog/branch/deep/data/file.tif')
    assert export('.metadata-download') == static_item
    assert export()['features'][0]['assets']['data']['href'] == host + '/catalog/branch/deep/data/file.tif'
    page.get_by_role('button', name='parent · Parent', exact=True).click()
    expect(page.locator('#catalog-summary')).to_contain_text('nested-branch')
    page.get_by_role('button', name='root · Root', exact=True).click()
    expect(page.locator('#endpoint')).to_have_value(host + '/catalog/root.json')
    expect(page.locator('#count')).to_have_text('0')
    page.unroute(host + '/**', fixture)
    print('Catalog compatibility passed: Earth Search/Planetary presets, JSON endpoints, and nested child/parent/root/item navigation.', flush=True)
