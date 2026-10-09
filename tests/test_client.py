"""Synthetic fixtures, not real population data; no network is used here."""
import asyncio
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "notebooks"))
from stac_browser import STACBrowser, PRESETS, date_range, https_url, next_request, validate_bbox, validate_polygon, explorer_url

CATALOG = json.loads((ROOT / "tests/fixtures/catalog.json").read_text(encoding="utf-8"))
ITEMS = json.loads((ROOT / "tests/fixtures/items.json").read_text(encoding="utf-8"))


class Fixture:
    def __init__(self, root=None):
        self.root = root or CATALOG
        self.calls = []

    async def __call__(self, request):
        self.calls.append(copy.deepcopy(request))
        path = urlsplit(request["url"]).path
        if path in ("", "/", "/catalog.json"):
            data = self.root
        elif path == "/collections":
            data = {"collections": [{"type": "Collection", "id": "TEST", "license": "proprietary", "title": "Synthetic test collection"}], "links": [{"rel": "next", "href": "./collections2"}]}
        elif path == "/collections2":
            data = {"collections": [{"id": "TEST"}, {"id": "OTHER"}], "links": []}
        elif path == "/search":
            query = request.get("body") or {k: v[-1] for k, v in parse_qs(urlsplit(request["url"]).query).items()}
            selected = query.get("collections")
            data = ITEMS if selected in ("TEST", ["TEST"]) else {"type": "FeatureCollection", "features": [{**ITEMS["features"][1], "id": "unfiltered-item", "collection": "OTHER"}], "links": []}
        elif path == "/page2":
            data = {"type": "FeatureCollection", "features": [ITEMS["features"][0], {**ITEMS["features"][1], "id": "synthetic-3"}], "links": []}
        elif path == "/item.json":
            data = ITEMS["features"][0]
        else:
            raise RuntimeError("Synthetic provider error")
        return copy.deepcopy(data), request["url"]


class ValidationTests(unittest.TestCase):
    def test_polygon_cases(self):
        cases = json.loads((ROOT / 'tests/fixtures/study-geometries.json').read_text())
        for ring in cases['valid']:
            self.assertEqual(validate_polygon({'type': 'Polygon', 'coordinates': [ring]})['coordinates'], [ring])
        for ring in cases['invalid']:
            with self.assertRaises(ValueError):
                validate_polygon({'type': 'Polygon', 'coordinates': [ring]})
        for value in [None, {}, {'type': 'MultiPolygon', 'coordinates': []}, {'type': 'Polygon', 'coordinates': cases['valid']}, {'type': 'Polygon', 'coordinates': [[[False, 0], [1, 0], [0, 1], [False, 0]]]}]:
            with self.assertRaises(ValueError):
                validate_polygon(value)
        for count in [500, 501]:
            ring = [[30 + math.cos(2 * math.pi * i / count), math.sin(2 * math.pi * i / count)] for i in range(count)]
            polygon = {'type': 'Polygon', 'coordinates': [ring + [ring[0][:]]]}
            if count == 500:
                self.assertEqual(validate_polygon(polygon), polygon)
            else:
                with self.assertRaisesRegex(ValueError, '3–500'):
                    validate_polygon(polygon)

    def test_https_urls(self):
        self.assertEqual(https_url("../items", "https://example.test/catalog/root.json"), "https://example.test/items")
        for url in ["http://example.test", "javascript:alert(1)", "https://name:pass@example.test", "file:///tmp/a"]:
            with self.assertRaises(ValueError):
                https_url(url)

    def test_bbox(self):
        self.assertEqual(validate_bbox([-180, -90, 180, 90]), [-180, -90, 180, 90])
        for bbox in [[1, 2, 0, 3], [0, 0, 181, 1], [0, -91, 1, 0], [0, 0, float("nan"), 1], [0, 1, 2], [False, 0, 1, 1]]:
            with self.assertRaises(ValueError):
                validate_bbox(bbox)

    def test_dates(self):
        self.assertIsNone(date_range())
        self.assertEqual(date_range("2024-02-29"), "2024-02-29T00:00:00Z/..")
        self.assertEqual(date_range(end="2024-02-29"), "../2024-02-29T23:59:59.999999Z")
        for dates in [("2023-02-29", None), ("2020-02-01", "2020-01-01"), ("20200101", None)]:
            with self.assertRaises(ValueError):
                date_range(*dates)

    def test_post_merge_and_replace(self):
        previous = {"url": "https://test.example/search", "method": "POST", "body": {"bbox": [0, 0, 1, 1], "limit": 2}}
        link = {"href": "./next", "method": "POST", "merge": True, "body": {"token": "a"}}
        self.assertEqual(next_request(link, previous)["body"], {"bbox": [0, 0, 1, 1], "limit": 2, "token": "a"})
        link["merge"] = False
        self.assertEqual(next_request(link, previous)["body"], {"token": "a"})
        with self.assertRaises(ValueError):
            next_request({"href": "./next", "method": "DELETE"}, previous)

    def test_iframe_frontend_relative(self):
        self.assertEqual(explorer_url(), "../../explorer/")


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_polygon_post_and_capture_before_response(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def fetch(req):
            calls.append(copy.deepcopy(req))
            if urlsplit(req['url']).path == '/':
                return {**CATALOG, 'links': [
                    {'rel': 'search', 'href': './get-search', 'method': 'GET'},
                    {'rel': 'search', 'href': './post-search?token=keep&bbox=stale', 'method': 'POST'},
                ]}, req['url']
            if req['method'] == 'POST':
                started.set()
                await release.wait()
            return copy.deepcopy(ITEMS), req['url']

        client = await STACBrowser('https://fixture.test/', fetch).connect()
        polygon = {'type': 'Polygon', 'coordinates': [[[30, -1], [33, -1], [32, 3], [30, -1]]]}
        expected = copy.deepcopy(polygon)
        snapshot = {'shape': 'polygon', 'geometry': copy.deepcopy(polygon)}
        pending = asyncio.create_task(client.search(intersects=polygon, study_area=snapshot))
        await asyncio.wait_for(started.wait(), 2)
        polygon['coordinates'][0][0][0] = 99
        snapshot['geometry']['coordinates'][0][1][0] = 99
        release.set()
        await pending
        req = calls[-1]
        self.assertEqual(urlsplit(req['url']).path, '/post-search')
        self.assertEqual(parse_qs(urlsplit(req['url']).query), {'token': ['keep']})
        self.assertEqual(req['body']['intersects'], expected)
        self.assertEqual(client.provenance()['query']['intersects'], expected)
        self.assertEqual(client.provenance()['study_area']['geometry'], expected)
        await client.search(bbox=[30, -1, 33, 3])
        self.assertEqual(calls[-1]['method'], 'GET')
        self.assertEqual(urlsplit(calls[-1]['url']).path, '/get-search')

    async def test_copernicus_collection_page_size_preserves_advertised_pagination(self):
        endpoint = "https://stac.dataspace.copernicus.eu/v1"
        self.assertEqual(PRESETS["copernicus"], endpoint)
        calls = []

        async def fetch(req):
            calls.append(req["url"])
            if req["url"] == endpoint:
                data = {**CATALOG, "links": [{"rel": "data", "href": endpoint + "/collections"}]}
            elif req["url"] == endpoint + "/collections?limit=1000":
                data = {"collections": [{"id": "sentinel-2-l2a"}], "links": [{"rel": "next", "href": "./collections?offset=1&limit=1"}]}
            elif req["url"] == endpoint + "/collections?offset=1&limit=1":
                data = {"collections": [{"id": "sentinel-1-grd"}], "links": []}
            else:
                self.fail(f"Unexpected request: {req}")
            return data, req["url"]

        client = await STACBrowser(PRESETS["copernicus"], fetch).connect()
        self.assertEqual(len(calls), 2)
        await client.more_collections()
        self.assertEqual([c["id"] for c in client.collections], ["sentinel-2-l2a", "sentinel-1-grd"])
        self.assertIsNone(client.collection_next)
        # Explicit provider parameters and other hosts are left untouched.
        for url in [endpoint + "/collections?limit=5", "https://fixture.test/collections"]:
            async def advertised(req):
                if req["url"] == endpoint:
                    return {**CATALOG, "links": [{"rel": "data", "href": url}]}, req["url"]
                self.assertEqual(req["url"], url)
                return {"collections": [], "links": []}, req["url"]
            await STACBrowser(endpoint, advertised).connect()

    async def test_search_pagination_provenance_and_collections(self):
        fake = Fixture()
        client = await STACBrowser("https://fixture.test/", fake).connect()
        self.assertEqual(len(client.collections), 1)
        await client.more_collections()
        self.assertEqual(len(client.collections), 2)
        await client.search([29, -2, 35, 5], collection="TEST", start="2020-01-01", end="2020-01-02", limit=2)
        query = parse_qs(urlsplit(fake.calls[-1]["url"]).query)
        self.assertEqual(query, {"bbox": ["29,-2,35,5"], "limit": ["2"], "collections": ["TEST"], "datetime": ["2020-01-01T00:00:00Z/2020-01-02T23:59:59.999999Z"]})
        self.assertEqual(len(client.items), 2)
        self.assertEqual(client.items[0]["id"], "synthetic-1")
        self.assertEqual(client.items[0]["collection"], "TEST")
        await client.more()
        self.assertEqual(len(client.items), 3)
        self.assertEqual(fake.calls[-1]["method"], "POST")
        self.assertEqual(fake.calls[-1]["body"], {"token": "second"})
        self.assertEqual(client.geojson()["features"][0]["assets"]["data"]["href"], "https://fixture.test/items/data.tif")
        self.assertEqual(client.items[0]["assets"], ITEMS["features"][0]["assets"])
        self.assertEqual(client.provenance()["count"], 3)
        self.assertEqual(len(client.provenance()["requests"]), 2)

    async def test_post_search(self):
        root = copy.deepcopy(CATALOG)
        root["links"][1]["method"] = "POST"
        fake = Fixture(root)
        client = await STACBrowser("https://fixture.test/", fake).connect()
        await client.search([0, 0, 1, 1], start="2024-02-29", limit=1)
        self.assertEqual(fake.calls[-1]["body"]["datetime"], "2024-02-29T00:00:00Z/..")

    async def test_existing_get_parameters_and_fragment(self):
        root = copy.deepcopy(CATALOG)
        root["links"][1]["href"] = "./search?limit=99&collections=OLD&collections=OLDER&bbox=1,1,2,2&datetime=old&token=keep#fragment"
        fake = Fixture(root)
        client = await STACBrowser("https://fixture.test/", fake).connect()
        await client.search([29, -2, 35, 5], collection="TEST", limit=2)
        parts = urlsplit(fake.calls[-1]["url"])
        self.assertEqual(parts.fragment, "")
        self.assertEqual(parse_qs(parts.query), {"token": ["keep"], "bbox": ["29,-2,35,5"], "limit": ["2"], "collections": ["TEST"]})
        self.assertEqual(client.items[0]["id"], "synthetic-1")

    async def test_reconnect_resets_state_and_failed_initialization_is_empty(self):
        fake = Fixture()
        client = await STACBrowser("https://fixture.test/", fake).connect()
        await client.search([29, -2, 35, 5], collection="TEST")
        self.assertTrue(client.next)
        self.assertTrue(client.collection_next)
        fake.root = {**CATALOG, "id": "new-static", "links": []}
        await client.connect("https://fixture.test/catalog.json")
        self.assertEqual(client.root["id"], "new-static")
        self.assertEqual(client.items, [])
        self.assertEqual(client.collections, [])
        self.assertEqual(client.requests, [])
        for value in (client.query, client.next, client.collection_next, client.retrieved_at, client.search_link):
            self.assertIsNone(value)
        fake.root = CATALOG
        await client.connect()
        await client.search([29, -2, 35, 5], collection="TEST")
        fake.root = {**CATALOG, "id": "partial-must-not-commit", "links": [{"rel": "data", "href": "./outage"}]}
        with self.assertRaisesRegex(RuntimeError, "Synthetic provider error"):
            await client.connect()
        self.assertIsNone(client.root)
        self.assertIsNone(client.url)
        self.assertEqual(client.items, [])
        self.assertEqual(client.collections, [])
        self.assertEqual(client.requests, [])
        self.assertEqual(client._item_locations, {})
        for value in (client.query, client.next, client.collection_next, client.retrieved_at, client.search_link):
            self.assertIsNone(value)
        count = len(fake.calls)
        await client.more()
        await client.more_collections()
        self.assertEqual(len(fake.calls), count)

    async def test_initial_collections_deduplicate_before_cap_and_ignore_invalid(self):
        async def fetch(req):
            if urlsplit(req["url"]).path == "/collections":
                return {"collections": [None, {}, {"id": ""}] + [{"id": "TEST"}] * 1001 + [{"id": "OTHER"}], "links": [None]}, req["url"]
            return {**CATALOG, "links": [None, *CATALOG["links"]]}, req["url"]
        client = await STACBrowser("https://fixture.test/", fetch).connect()
        self.assertEqual([c["id"] for c in client.collections], ["TEST", "OTHER"])

    async def test_export_bases_pagination_null_entries_and_acquisition_time(self):
        first = {"type": "Feature", "id": "self", "stac_version": "1.0.0", "properties": {}, "geometry": None,
                 "links": [None, {"rel": "self", "href": "./items/x.json"}, {"rel": "about", "href": "./about.json"}],
                 "assets": {"data": {"href": "./data.tif"}, "invalid": None}}
        second = {**first, "id": "no-self", "links": [{"rel": "about", "href": "./about.json"}]}
        third = {**second, "id": "page-two"}
        async def fetch(req):
            path = urlsplit(req["url"]).path
            if path == "/root.json":
                value = {**CATALOG, "links": [{"rel": "search", "href": "./one/search"}]}
            elif path == "/one/search":
                value = {"type": "FeatureCollection", "features": [None, copy.deepcopy(first), {}, copy.deepcopy(second)], "links": [None, {"rel": "next", "href": "../two/search"}]}
            else:
                value = {"type": "FeatureCollection", "features": [copy.deepcopy(third)], "links": [None]}
            return value, req["url"]
        client = await STACBrowser("https://fixture.test/root.json", fetch).connect()
        with patch("stac_browser.datetime") as clock:
            clock.now.return_value.isoformat.return_value = "2026-10-06T12:00:00+00:00"
            await client.search([0, 0, 1, 1])
        self.assertEqual(client.provenance()["retrieved_at"], "2026-10-06T12:00:00+00:00")
        self.assertEqual(client.provenance(), client.provenance())
        with patch("stac_browser.datetime") as clock:
            clock.now.return_value.isoformat.return_value = "2026-10-06T12:01:00+00:00"
            await client.more()
        exported = client.geojson()["features"]
        self.assertEqual(len(exported), 3)
        self.assertEqual(exported[0]["links"][1]["href"], "https://fixture.test/one/items/x.json")
        self.assertEqual(exported[0]["links"][2]["href"], "https://fixture.test/one/items/about.json")
        self.assertEqual(exported[0]["assets"]["data"]["href"], "https://fixture.test/one/items/data.tif")
        self.assertEqual(exported[1]["assets"]["data"]["href"], "https://fixture.test/one/data.tif")
        self.assertEqual(exported[2]["assets"]["data"]["href"], "https://fixture.test/two/data.tif")
        self.assertEqual(client.items[0], first)
        self.assertEqual(client.items[1], second)
        self.assertEqual(client.provenance()["retrieved_at"], "2026-10-06T12:01:00+00:00")
        exported[0]["properties"]["changed"] = True
        self.assertEqual(client.items[0]["properties"], {})

    async def test_static_catalog_and_item(self):
        root = {**CATALOG, "links": [{"rel": "item", "href": "./item.json"}]}
        client = await STACBrowser("https://fixture.test/catalog.json", Fixture(root)).connect()
        with self.assertRaisesRegex(ValueError, "Static catalog"):
            await client.search([0, 0, 1, 1])
        item = await client.open_link(client.browse_links()[0])
        self.assertEqual(item["id"], "synthetic-1")
        self.assertEqual(client.provenance()["count"], 1)

    async def test_errors_and_validation_before_network(self):
        with self.assertRaisesRegex(ValueError, "Expected a STAC"):
            await STACBrowser("https://fixture.test/", Fixture({"type": "wrong"})).connect()
        fake = Fixture()
        client = await STACBrowser("https://fixture.test/", fake).connect()
        count = len(fake.calls)
        with self.assertRaises(ValueError):
            await client.search([0, 0, 1, 1], limit=1000)
        self.assertEqual(len(fake.calls), count)
        with self.assertRaises(ValueError):
            client.save()

    async def test_cap(self):
        async def many(req):
            if urlsplit(req["url"]).path == "/search":
                return {"type": "FeatureCollection", "features": [{"type": "Feature", "id": str(n)} for n in range(700)], "links": [{"rel": "next", "href": "./next"}]}, req["url"]
            return {**CATALOG, "links": [CATALOG["links"][1]]}, req["url"]
        client = await STACBrowser("https://fixture.test/", many).connect()
        await client.search([0, 0, 1, 1], limit=100)
        self.assertEqual(len(client.items), 500)
        self.assertIsNone(client.next)

    async def test_optional_spatial_filters_and_completed_snapshots(self):
        polygon = {'type': 'Polygon', 'coordinates': [[[30, -1], [33, -1], [32, 3], [30, -1]]]}
        for method in ('GET', 'POST'):
            root = {**CATALOG, 'links': [{'rel': 'search', 'href': './search?bbox=old&intersects=old&token=keep', 'method': method}]}
            fake = Fixture(root)
            client = await STACBrowser('https://fixture.test/', fake).connect()
            for mode, spatial in [('bbox', {'bbox': [-180, -90, 180, 90]}), ('polygon', {'intersects': polygon}), ('none', {})]:
                snapshot = {'shape': 'polygon', 'geometry': copy.deepcopy(polygon), 'bbox': [30, -1, 33, 3]}
                await client.search(**spatial, collection='TEST', start='2024-01-01', limit=2, study_area=snapshot)
                req = fake.calls[-1]
                if method == 'POST':
                    self.assertNotIn('bbox', parse_qs(urlsplit(req['url']).query))
                    self.assertNotIn('intersects', parse_qs(urlsplit(req['url']).query))
                sent = req['body'] if method == 'POST' else {k: v[-1] for k, v in parse_qs(urlsplit(req['url']).query).items()}
                self.assertEqual('bbox' in sent, mode == 'bbox')
                self.assertEqual('intersects' in sent, mode == 'polygon')
                if mode == 'polygon':
                    self.assertEqual(sent['intersects'] if method == 'POST' else json.loads(sent['intersects']), polygon)
                self.assertEqual(client.provenance()['spatial_mode'], mode)
                self.assertTrue(sent['collections'] and sent['datetime'] and sent['limit'])
                snapshot['geometry']['coordinates'][0][0][0] = 10
                self.assertEqual(client.provenance()['study_area']['geometry']['coordinates'][0][0][0], 30)
                previous = client.provenance()
                client.search_link['href'] = './failure'
                with self.assertRaises(RuntimeError):
                    await client.search(intersects=polygon)
                self.assertEqual(client.provenance(), previous)
                client.search_link['href'] = './search'
            count = len(fake.calls)
            with self.assertRaises(ValueError):
                await client.search(bbox=[0, 0, 1, 1], intersects=polygon)
            with self.assertRaises(ValueError):
                await client.search(intersects={'type': 'Polygon', 'coordinates': []})
            self.assertEqual(len(fake.calls), count)




class DigitalEarthAfricaTests(unittest.IsolatedAsyncioTestCase):
    async def test_featured_endpoint_and_bounded_madagascar_search(self):
        endpoint = 'https://explorer.digitalearth.africa/stac/'
        self.assertEqual(PRESETS['deafrica'], endpoint)
        calls = []
        async def fetch(request):
            calls.append(request)
            path = urlsplit(request['url']).path
            if path == '/stac/':
                data = {**CATALOG, 'links': [{'rel': 'data', 'href': './collections'}, {'rel': 'search', 'href': './search'}]}
            elif path == '/stac/collections':
                data = {'collections': [{'id': 's2_l2a'}], 'links': []}
            else:
                data = {'type': 'FeatureCollection', 'features': [], 'links': []}
            return data, request['url']
        client = await STACBrowser(endpoint, fetch).connect()
        await client.search(collection='s2_l2a', bbox=[45, -20.1, 47, -19.8], start='2020-01-01', end='2020-01-31', limit=3)
        self.assertEqual(calls[0]['url'], endpoint)
        self.assertEqual(parse_qs(urlsplit(calls[-1]['url']).query), {
            'collections': ['s2_l2a'], 'bbox': ['45,-20.1,47,-19.8'], 'limit': ['3'],
            'datetime': ['2020-01-01T00:00:00Z/2020-01-31T23:59:59.999999Z']})


if __name__ == "__main__":
    unittest.main()
