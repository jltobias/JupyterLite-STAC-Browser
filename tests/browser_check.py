"""Browser regression against synthetic fixtures, served at root or a repo subpath."""
import argparse
import copy
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect
from study_area_check import check_study_area

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "tests/fixtures/catalog.json").read_text(encoding="utf-8"))
ITEMS = json.loads((ROOT / "tests/fixtures/items.json").read_text(encoding="utf-8"))
COPERNICUS_ITEM = json.loads((ROOT / "tests/fixtures/copernicus-item.json").read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-path", default="")
    parser.add_argument("--chrome", help="Optional installed Chrome executable")
    parser.add_argument("--live", action="store_true", help="Also smoke-test current WorldPop and Copernicus via browser CORS")
    parser.add_argument("--source", action="store_true", help="Test explorer source without rebuilding the combined site")
    args = parser.parse_args()
    base = args.base_path.rstrip("/")

    class Handler(SimpleHTTPRequestHandler):
        def translate_path(self, path):
            if base and path.startswith(base + "/"):
                path = path[len(base):]
            if args.source and path.startswith("/explorer/"):
                path = "/web/" + path[len("/explorer/"):]
            return super().translate_path(path)
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT if args.source else ROOT / "_site")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_port}{base}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, **({"executable_path": args.chrome} if args.chrome else {}))
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, timezone_id="America/Los_Angeles")
            # October 8 locally, October 9 in UTC: Until must use the visitor's date.
            page.clock.set_fixed_time(datetime(2026, 10, 9, 2, tzinfo=timezone.utc))
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("pageerror", lambda error: print('Browser error:', error, flush=True))
            calls = []
            pending_connections = []

            def fixture(route):
                req = route.request
                path = urlsplit(req.url).path
                calls.append({"url": req.url, "method": req.method, "body": req.post_data})
                headers = {"Access-Control-Allow-Origin": "*"}
                if path in ("/", ""):
                    data = CATALOG
                elif path == "/delayed":
                    pending_connections.append(route)
                    return
                elif path == "/capped":
                    data = {**CATALOG, "links": [{"rel": "data", "href": "./capped-collections"}]}
                elif path == "/capped-collections":
                    data = {"collections": [{"id": f"CAP-{i}", "extent": {"temporal": {"interval": [["2020-01-01T00:00:00Z", None]]}}} for i in range(1000)], "links": [{"rel": "next", "href": "./unloaded-older-collections"}]}
                elif path == "/collections":
                    data = {"collections": [
                        {"id": "TEST", "title": "Synthetic fixture", "license": "proprietary", "providers": [{"name": "Fixture provider"}], "extent": {"temporal": {"interval": [["2020-01-01T00:00:00Z", None]]}, "spatial": {"bbox": [[29.123456789, -2, 35.987654321, 5]]}}},
                        {"id": "OTHER", "extent": {"temporal": {"interval": [["2010-06-15T00:00:00Z", None]]}, "spatial": {"bbox": [[-123, 37, 100, -121, 39, 900]]}}},
                    ], "links": [{"rel": "next", "href": "./collections2"}]}
                elif path == "/collections2":
                    data = {"collections": [{"id": "EARLY", "extent": {"temporal": {"interval": [["1985-02-03T00:00:00Z", None]]}}}], "links": []}
                elif path == "/search":
                    if parse_qs(urlsplit(req.url).query).get("collections") == ["TEST"]:
                        data = copy.deepcopy(ITEMS)
                        data["features"].append(None)
                        data["features"][0]["assets"]["invalid"] = None
                        data["features"][0]["links"].append(None)
                        data["features"][0]["properties"].update({"year": 2020, "project": "Synthetic population project"})
                    else:
                        data = {"type": "FeatureCollection", "features": [{**ITEMS["features"][1], "id": "unfiltered-item", "collection": "OTHER"}], "links": []}
                elif path == "/page2":
                    data = {"type": "FeatureCollection", "features": [ITEMS["features"][0], {**ITEMS["features"][1], "id": "synthetic-3"}], "links": []}
                elif path == "/static.json":
                    data = {**CATALOG, "links": [{"rel": "item", "href": "./item.json", "title": "Synthetic static item"}]}
                elif path == "/collection.json":
                    data = {**CATALOG, "type": "Collection", "id": "MISSING", "links": []}
                elif path == "/dated-collection.json":
                    data = {**CATALOG, "type": "Collection", "id": "DATED", "extent": {"temporal": {"interval": [["2012-04-05T00:00:00Z", None]]}}, "links": []}
                elif path == "/crossing-collection.json":
                    data = {**CATALOG, "type": "Collection", "id": "CROSSING", "extent": {"spatial": {"bbox": [[170, -10, -170, 10]]}}, "links": [{"rel": "search", "href": "./search"}]}
                elif path == "/point-collection.json":
                    data = {**CATALOG, "type": "Collection", "id": "POINT", "extent": {"spatial": {"bbox": [[30, 0, 30, 0]]}}, "links": [{"rel": "search", "href": "./search"}]}
                elif path == "/spatial-static.json":
                    data = {**CATALOG, "type": "Collection", "id": "STATIC", "extent": {"spatial": {"bbox": [[-123, 37, -121, 39]]}}, "links": [{"rel": "item", "href": "./item.json"}]}
                elif path == "/item.json":
                    data = ITEMS["features"][0]
                elif path == "/wrong":
                    data = {"type": "FeatureCollection", "features": []}
                elif path == "/collection-failure":
                    data = {**CATALOG, "links": [{"rel": "data", "href": "./missing-collections"}]}
                elif path == "/nonjson":
                    route.fulfill(status=200, body="<html>Not JSON</html>", content_type="text/html", headers=headers)
                    return
                else:
                    route.fulfill(status=503, body='{"error":"Synthetic provider outage"}', content_type="application/json", headers=headers)
                    return
                route.fulfill(status=200, body=json.dumps(data), content_type="application/json", headers=headers)

            page.route("https://api.stac.worldpop.org/**", fixture)
            page.route("https://fixture.test/**", fixture)
            copernicus = "https://stac.dataspace.copernicus.eu/v1"

            def copernicus_fixture(route):
                req = route.request
                calls.append({"url": req.url, "method": req.method, "body": req.post_data})
                parts = urlsplit(req.url)
                if req.url == copernicus:
                    data = {**CATALOG, "links": [{"rel": "data", "href": copernicus + "/collections"}, {"rel": "search", "href": copernicus + "/search"}]}
                elif req.url == copernicus + "/collections?limit=1000":
                    data = {"collections": [
                        {"id": "sentinel-2-l2a", "title": "Sentinel-2 Level-2A", "license": "proprietary", "providers": [{"name": "Copernicus fixture provider"}], "extent": {"spatial": {"bbox": [[-180, -90, 180, 90]]}, "temporal": {"interval": [["2015-06-27T00:00:00Z", None]]}}},
                        {"id": "ccm-optical", "title": "CCM optical"},
                    ], "links": [{"rel": "next", "href": copernicus + "/collections?offset=2&limit=2"}]}
                elif req.url == copernicus + "/collections?offset=2&limit=2":
                    data = {"collections": [{"id": "sentinel-1-grd", "title": "Sentinel-1 GRD"}], "links": []}
                elif parts.path == "/v1/search":
                    data = {"type": "FeatureCollection", "features": [COPERNICUS_ITEM], "links": []}
                else:
                    raise AssertionError(f"Unexpected Copernicus request: {req.url}")
                route.fulfill(status=200, body=json.dumps(data), content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})

            page.route("https://stac.dataspace.copernicus.eu/**", copernicus_fixture)
            page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
            page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
            page.goto(address + "/explorer/")
            expect(page.locator("#search")).to_be_enabled(timeout=15000)
            expect(page.locator("#more-collections")).to_be_visible()
            expect(page.locator("#start")).to_have_value("2000-01-01")
            expect(page.locator("#end")).to_have_value("2026-10-08")
            page.locator("#more-collections").click()
            expect(page.locator("#start")).to_have_value("1985-02-03")
            page.locator("#connect").click()
            expect(page.locator("#more-collections")).to_be_visible()
            expect(page.locator("#search")).to_be_enabled()
            page.evaluate("""() => {
              const fit = L.Map.prototype.fitBounds;
              L.Map.prototype.fitBounds = function(...args) {window.previewMap = this; return fit.apply(this, args);};
            }""")
            searches_before_selection = len([call for call in calls if urlsplit(call["url"]).path == "/search"])
            page.locator("#collection").select_option("TEST")
            expect(page.locator("#start")).to_have_value("2020-01-01")
            expect(page.locator("#bbox")).to_have_value("29.123456789,-2,35.987654321,5")
            assert page.evaluate("""() => {
              const m=window.previewMap, b=m.getBounds(), c=m.getCenter();
              return m.getZoom()>5 && b.contains([[-2,29.123456789],[5,35.987654321]]) && c.lng>29 && c.lng<36;
            }""")
            assert len([call for call in calls if urlsplit(call["url"]).path == "/search"]) == searches_before_selection
            page.locator("#start").fill("2019-01-01")
            page.locator("#end").fill("2020-03-04")
            page.locator("#bbox").fill("1,2,3,4")
            view_before_pagination = page.evaluate("[previewMap.getCenter().lat,previewMap.getCenter().lng,previewMap.getZoom()]")
            page.locator("#more-collections").click()
            expect(page.locator("#more-collections")).to_be_hidden()
            expect(page.locator("#start")).to_have_value("2019-01-01")
            expect(page.locator("#end")).to_have_value("2020-03-04")
            expect(page.locator("#bbox")).to_have_value("1,2,3,4")
            assert page.evaluate("[previewMap.getCenter().lat,previewMap.getCenter().lng,previewMap.getZoom()]") == view_before_pagination
            page.locator("#collection").select_option("OTHER")
            expect(page.locator("#start")).to_have_value("2010-06-15")
            expect(page.locator("#end")).to_have_value("2026-10-08")
            expect(page.locator("#bbox")).to_have_value("1,2,3,4")
            page.locator("#collection-area").click()
            expect(page.locator("#bbox")).to_have_value("-123,37,-121,39")
            assert page.evaluate("previewMap.getBounds().contains([[37,-123],[39,-121]]) && previewMap.getCenter().lng < -121")
            selected_view = page.evaluate("[previewMap.getCenter().lat,previewMap.getCenter().lng,previewMap.getZoom()]")
            page.locator("#collection").select_option("EARLY")
            expect(page.locator("#status")).to_contain_text("no usable spatial extent")
            expect(page.locator("#bbox")).to_have_value("-123,37,-121,39")
            assert page.evaluate("[previewMap.getCenter().lat,previewMap.getCenter().lng,previewMap.getZoom()]") == selected_view
            page.locator("#collection").select_option("")
            expect(page.locator("#start")).to_have_value("1985-02-03")
            expect(page.locator("#bbox")).to_have_value("-123,37,-121,39")
            assert page.evaluate("[previewMap.getCenter().lat,previewMap.getCenter().lng,previewMap.getZoom()]") == selected_view
            page.locator("#collection").select_option("TEST")
            expect(page.locator("#start")).to_have_value("2020-01-01")
            page.locator("#start").fill("")
            page.locator("#end").fill("")
            page.locator("#use-map").click()
            assert page.locator("#bbox").input_value() != "29.123456789,-2,35.987654321,5"
            assert page.evaluate("""() => {
              const [w,s,e,n]=document.querySelector('#bbox').value.split(',').map(Number);
              return w<=29.123456789 && s<=-2 && e>=35.987654321 && n>=5;
            }""")
            expect(page.locator("#start")).to_have_value("")
            expect(page.locator("#end")).to_have_value("")
            page.locator("#bbox").fill("29,-2,35,5")
            page.locator("#start").fill("2020-01-01")
            page.locator("#end").fill("2020-01-02")
            page.locator("#search").click()
            expect(page.locator(".result-card")).to_have_count(2)
            search_call = next(call for call in reversed(calls) if urlsplit(call["url"]).path == "/search")
            assert parse_qs(urlsplit(search_call["url"]).query) == {"bbox": ["29,-2,35,5"], "limit": ["25"], "collections": ["TEST"], "datetime": ["2020-01-01T00:00:00Z/2020-01-02T23:59:59.999999Z"]}
            coverage = page.locator("#map path.result-footprint")
            expect(coverage).to_have_count(1)
            expect(coverage.first).to_be_visible()
            assert coverage.first.get_attribute("fill-opacity") == "0"
            coverage.first.click()
            expect(page.locator("#metadata h3").first).to_contain_text("<img src=x")
            expect(page.locator("#metadata")).to_contain_text("synthetic-1")
            expect(page.locator("#metadata")).to_contain_text("Reference year")
            expect(page.locator("#metadata")).to_contain_text("2020")
            expect(page.locator("#metadata")).to_contain_text("Synthetic population project")
            assert coverage.first.get_attribute("fill-opacity") == "0.12"
            assert page.locator("#metadata img, #metadata script").count() == 0
            assert page.locator("#metadata a[href^='javascript:']").count() == 0
            assert page.locator("#metadata a").first.get_attribute("href").endswith("/items/data.tif")
            assert page.locator("#metadata").get_by_role("link", name="self", exact=True).get_attribute("href").endswith("/items/synthetic-1.json")
            expect(page.locator("#metadata")).to_contain_text("Fixture provider")
            page.locator("#more").click()
            expect(page.locator(".result-card")).to_have_count(3)
            assert calls[-1]["method"] == "POST" and json.loads(calls[-1]["body"])["token"] == "second"
            page.locator(".result-card").first.click()
            assert page.locator("#metadata a").first.get_attribute("href").endswith("/items/data.tif")
            for button, expected in [("#export-geojson", "FeatureCollection"), ("#export-query", None)]:
                with page.expect_download() as download_info:
                    page.locator(button).click()
                data = json.loads(Path(download_info.value.path()).read_text())
                assert data["type"] == expected if expected else data["count"] == 3
            page.locator("#search").click()
            expect(page.locator("#metadata")).to_contain_text("Select one of the new results")
            page.locator("#bbox").fill("180,0,-180,10")
            page.locator("#search").click()
            expect(page.locator("#status")).to_contain_text("Bbox must")
            old_bbox = page.locator("#bbox").input_value()
            page.evaluate("""() => {window.originalGetBounds = L.Map.prototype.getBounds; L.Map.prototype.getBounds = () => ({getWest:()=>170,getSouth:()=>-10,getEast:()=>190,getNorth:()=>10});}""")
            page.locator("#use-map").click()
            expect(page.locator("#status")).to_contain_text("crosses the antimeridian")
            assert page.locator("#bbox").input_value() == old_bbox
            page.evaluate("""() => {L.Map.prototype.getBounds = () => ({getWest:()=>-220,getSouth:()=>-95,getEast:()=>220,getNorth:()=>95});}""")
            page.locator("#use-map").click()
            expect(page.locator("#bbox")).to_have_value("-180,-90,180,90")
            global_calls = len(calls)
            page.locator('#spatial-mode').select_option('polygon')
            page.locator('#search').click()
            expect(page.locator('#status')).to_contain_text('antimeridian')
            assert len(calls) == global_calls
            page.locator('#spatial-mode').select_option('bbox')
            page.locator('#search').click()
            expect(page.locator('#search')).to_be_enabled()
            assert parse_qs(urlsplit(calls[-1]['url']).query)['bbox'] == ['-180,-90,180,90']
            page.evaluate("() => {L.Map.prototype.getBounds = window.originalGetBounds; delete window.originalGetBounds;}")
            for endpoint, message in [("collection-failure", "HTTP 503"), ("wrong", "not a STAC"), ("nonjson", "non-JSON"), ("fail", "HTTP 503")]:
                page.locator("#endpoint").fill("https://fixture.test/" + endpoint)
                page.locator("#connect").click()
                expect(page.locator("#status")).to_contain_text(message)
                expect(page.locator("#connect")).to_be_enabled()
                expect(page.locator("#collection")).to_be_disabled()
                expect(page.locator("#collection option")).to_have_count(1)
                expect(page.locator("#more-collections")).to_be_hidden()
                expect(page.locator("#more-collections")).to_be_disabled()
                expect(page.locator("#start")).to_have_value("2000-01-01")
                expect(page.locator("#end")).to_have_value("2026-10-08")
            page.locator("#endpoint").fill("https://fixture.test/static.json")
            page.locator("#connect").click()
            expect(page.locator("#status")).to_contain_text("Static catalog connected")
            expect(page.locator("#search")).to_be_disabled()
            page.locator("#catalog-links button").first.click()
            expect(page.locator("#count")).to_have_text("1")
            expect(page.locator("#export-query")).to_be_enabled()
            expect(page.locator("#metadata")).to_contain_text("Not supplied — consult provider")
            for endpoint, expected in [("collection.json", "2000-01-01"), ("dated-collection.json", "2012-04-05")]:
                page.locator("#endpoint").fill("https://fixture.test/" + endpoint)
                page.locator("#connect").click()
                expect(page.locator("#status")).to_contain_text("Static catalog connected")
                expect(page.locator("#start")).to_have_value(expected)
                expect(page.locator("#end")).to_have_value("2026-10-08")
            page.locator("#endpoint").fill("https://fixture.test/crossing-collection.json")
            page.locator("#connect").click()
            expect(page.locator("#collection")).to_be_enabled()
            page.locator("#collection").select_option("CROSSING")
            expect(page.locator("#bbox")).to_have_value("-180,-90,180,90")
            expect(page.locator("#status")).to_contain_text("crosses the antimeridian")
            assert page.evaluate("Math.abs(previewMap.getCenter().lng-180)<0.1 && previewMap.getBounds().contains([[-10,170],[10,190]])")
            page.locator("#endpoint").fill("https://fixture.test/point-collection.json")
            page.locator("#connect").click()
            expect(page.locator("#collection")).to_be_enabled()
            page.locator("#collection").select_option("POINT")
            expect(page.locator("#bbox")).to_have_value("-180,-90,180,90")
            expect(page.locator("#status")).to_contain_text("point or line")
            assert page.evaluate("Math.abs(previewMap.getCenter().lng-30)<0.001 && Math.abs(previewMap.getCenter().lat)<0.001 && previewMap.getZoom()===12")
            page.locator("#use-map").click()
            assert page.locator("#bbox").input_value() != "30,0,30,0"
            page.locator("#endpoint").fill("https://fixture.test/spatial-static.json")
            page.locator("#connect").click()
            expect(page.locator("#collection")).to_be_enabled()
            page.locator("#collection").select_option("STATIC")
            expect(page.locator("#status")).to_contain_text("remote search is unavailable")
            expect(page.locator("#status")).not_to_contain_text("Select Search")
            page.locator("#collection-area").click()
            expect(page.locator("#bbox")).to_have_value("-123,37,-121,39")
            expect(page.locator("#search")).to_be_disabled()
            page.locator("#endpoint").fill("https://fixture.test/delayed")
            page.locator("#connect").click()
            expect(page.locator("#start")).to_be_disabled()
            expect(page.locator("#end")).to_be_disabled()
            assert len(pending_connections) == 1
            pending_connections.pop().fulfill(status=200, body=json.dumps(CATALOG), content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})
            expect(page.locator("#search")).to_be_enabled()
            expect(page.locator("#start")).to_be_enabled()
            expect(page.locator("#end")).to_be_enabled()
            page.locator("#endpoint").fill("https://fixture.test/capped")
            page.locator("#connect").click()
            expect(page.locator("#catalog-summary")).to_contain_text("1000 collections loaded")
            expect(page.locator("#start")).to_have_value("2000-01-01")
            page.locator("#collection").select_option("CAP-0")
            expect(page.locator("#start")).to_have_value("2020-01-01")
            protocol = page.evaluate("""async () => {
              const {safeURL,bboxValue,dateRange,nextRequest,fetchJSON} = await import('./stac.js');
              const rejects = fn => {try {fn(); return false;} catch {return true;}};
              if(!rejects(()=>safeURL('javascript:alert(1)')) || !rejects(()=>bboxValue('0,,1,2')) || !rejects(()=>dateRange('2023-02-29'))) throw Error('validation failed');
              const next=nextRequest({href:'./next',method:'POST',merge:true,body:{token:2}}, {url:'https://fixture.test/search',body:{limit:1}});
              if(next.body.limit!==1 || next.body.token!==2) throw Error('POST merge failed');
              let timedout=false;
              try {await fetchJSON({url:'https://fixture.test/'}, (_, options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')))), 5);} catch(e){timedout=e.message.includes('timed out');}
              if(!timedout) throw Error('timeout handling failed');
              return true;
            }""")
            assert protocol
            check_study_area(page, calls)
            # Switching from WorldPop to the second preset uses the real provider URL shape.
            assert page.locator("#preset option").evaluate_all("els => els.map(e=>e.value)") == ["worldpop", "copernicus", "earthsearch", "planetary", "custom"]
            page.locator("#preset").select_option("copernicus")
            expect(page.locator("#endpoint")).to_have_value(copernicus)
            page.locator("#connect").click()
            expect(page.locator("#collection option")).to_have_count(3)
            assert page.locator("#collection option").evaluate_all("els => els.map(e=>e.value)") == ["", "ccm-optical", "sentinel-2-l2a"]
            page.locator("#collection").select_option("sentinel-2-l2a")
            expect(page.locator("#start")).to_have_value("2015-06-27")
            expect(page.locator("#end")).to_have_value("2026-10-08")
            page.locator("#collection-area").click()
            expect(page.locator("#bbox")).to_have_value("-180,-90,180,90")
            page.locator("#more-collections").click()
            expect(page.locator("#more-collections")).to_be_hidden()
            expect(page.locator("#collection")).to_have_value("sentinel-2-l2a")
            assert page.locator("#collection option").evaluate_all("els => els.map(e=>e.value)") == ["", "ccm-optical", "sentinel-1-grd", "sentinel-2-l2a"]
            page.locator("#bbox").fill("2.2,48.7,2.5,49")
            page.locator("#start").fill("2024-06-01")
            page.locator("#end").fill("2024-06-15")
            page.locator("#limit").select_option("10")
            page.locator("#search").click()
            expect(page.locator(".result-card")).to_have_count(1)
            assert calls[-1]["url"].startswith(copernicus + "/search?")
            assert parse_qs(urlsplit(calls[-1]["url"]).query) == {"bbox": ["2.2,48.7,2.5,49"], "collections": ["sentinel-2-l2a"], "datetime": ["2024-06-01T00:00:00Z/2024-06-15T23:59:59.999999Z"], "limit": ["10"]}
            page.locator(".result-card").click()
            expect(page.locator("#metadata")).to_contain_text("synthetic-sentinel-2")
            expect(page.locator("#metadata dl")).to_contain_text("proprietary")
            expect(page.locator("#metadata dl")).to_contain_text("Copernicus fixture provider")
            red = page.locator("#metadata").get_by_role("link", name="Red band (HTTPS)", exact=True)
            expect(red).to_have_attribute("href", "https://fixture.test/download/red.jp2")
            expect(red.locator("..")).to_contain_text("Provider authentication required")
            expect(page.locator("#metadata").get_by_role("link", name="Product", exact=True).locator("..")).to_contain_text("Provider authentication required")
            expect(page.locator("#metadata")).to_contain_text("S3 only (S3; use a compatible client)")
            assert page.locator("#metadata a[href^='javascript:'], #metadata a[href^='s3:']").count() == 0
            assert page.locator("#metadata a").count() == 2
            with page.expect_download() as download_info:
                page.locator("#export-geojson").click()
            exported = json.loads(Path(download_info.value.path()).read_text())
            assert exported["features"][0]["assets"] == COPERNICUS_ITEM["assets"]
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            output = ROOT / "test-results"
            output.mkdir(exist_ok=True)
            page.screenshot(path=str(output / "explorer-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            if not args.source:
                page.goto(address + "/")
                for href in ["explorer/", "lite/lab/index.html?path=01_launch_map.ipynb", "book/"]:
                    assert page.locator(f'a[href="{href}"]').count() == 1
                page.goto(address + "/book/")
                expect(page.locator("body")).to_contain_text("A world of data")
                book_explorer = page.get_by_role("link", name="Explorer", exact=True).first
                assert page.evaluate("href => new URL(href, location.href).pathname", book_explorer.get_attribute("href")) == base + "/explorer"
                book_notebooks = page.get_by_role("link", name="Run notebooks", exact=True).first
                assert page.evaluate("href => new URL(href, location.href).pathname", book_notebooks.get_attribute("href")) == base + "/lite/lab/index.html"
            if args.live:
                page.unroute("https://api.stac.worldpop.org/**", fixture)
                live = page.evaluate("""async () => {const root=await fetch('https://api.stac.worldpop.org').then(r=>r.json());const response=await fetch('https://api.stac.worldpop.org/search?collections=UGA&bbox=29,-2,35,5&limit=1');const items=await response.json();return {root:root.type,status:response.status,count:items.features?.length};}""")
                assert live == {"root": "Catalog", "status": 200, "count": 1}, live
                print("Live WorldPop browser CORS smoke:", live)
                polygon_live = page.evaluate("""async moduleURL => {
                  const {STACClient,PRESETS}=await import(moduleURL);
                  const client=new STACClient(); await client.connect(PRESETS.worldpop[1]);
                  await client.search({collection:'UGA',intersects:{type:'Polygon',coordinates:[[[30,-1],[33,-1],[32,3],[30,-1]]]},limit:1});
                  return {count:client.items.length,mode:client.provenance().spatial_mode};
                }""", address + "/explorer/stac.js")
                assert polygon_live == {'count': 1, 'mode': 'polygon'}, polygon_live
                print('Live WorldPop polygon search:', polygon_live)
                page.unroute("https://stac.dataspace.copernicus.eu/**", copernicus_fixture)
                live = page.evaluate("""async moduleURL => {
                  const {STACClient,PRESETS}=await import(moduleURL);
                  const client=new STACClient(); await client.connect(PRESETS.copernicus[1]);
                  if(!client.collections.some(c=>c.id==='sentinel-2-l2a')) throw Error('Sentinel-2 collection missing');
                  await client.search({collection:'sentinel-2-l2a',bbox:[2.2,48.7,2.5,49],start:'2024-06-01',end:'2024-06-15',limit:1});
                  const first=client.items[0]?.id;
                  if(!first || !client.next) throw Error('Expected a result and next page');
                  await client.more();
                  const count=client.items.length;
                  await client.search({collection:'sentinel-2-l2a',intersects:{type:'Polygon',coordinates:[[[2.2,48.7],[2.5,48.7],[2.35,49],[2.2,48.7]]]},start:'2024-06-01',end:'2024-06-15',limit:1});
                  return {collections:client.collections.length,first,count,polygonCount:client.items.length};
                }""", address + "/explorer/stac.js")
                assert live["count"] == 2, live
                assert live['polygonCount'] == 1, live
                print("Live Copernicus browser CORS smoke:", live)
            assert not errors, errors
            browser.close()
        print("Browser fixture tests passed: protocol, UI, escaping, static catalogs, exports, recovery, responsive layout" + ("." if args.source else ", and site navigation."))
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
