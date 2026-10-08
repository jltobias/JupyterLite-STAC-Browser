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

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "tests/fixtures/catalog.json").read_text(encoding="utf-8"))
ITEMS = json.loads((ROOT / "tests/fixtures/items.json").read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-path", default="")
    parser.add_argument("--chrome", help="Optional installed Chrome executable")
    parser.add_argument("--live", action="store_true", help="Also smoke-test current WorldPop via browser CORS")
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
                        {"id": "TEST", "title": "Synthetic fixture", "license": "proprietary", "providers": [{"name": "Fixture provider"}], "extent": {"temporal": {"interval": [["2020-01-01T00:00:00Z", None]]}}},
                        {"id": "OTHER", "extent": {"temporal": {"interval": [["2010-06-15T00:00:00Z", None]]}}},
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
            page.locator("#collection").select_option("TEST")
            expect(page.locator("#start")).to_have_value("2020-01-01")
            page.locator("#start").fill("2019-01-01")
            page.locator("#end").fill("2020-03-04")
            page.locator("#more-collections").click()
            expect(page.locator("#more-collections")).to_be_hidden()
            expect(page.locator("#start")).to_have_value("2019-01-01")
            expect(page.locator("#end")).to_have_value("2020-03-04")
            page.locator("#collection").select_option("OTHER")
            expect(page.locator("#start")).to_have_value("2010-06-15")
            expect(page.locator("#end")).to_have_value("2026-10-08")
            page.locator("#collection").select_option("")
            expect(page.locator("#start")).to_have_value("1985-02-03")
            page.locator("#collection").select_option("TEST")
            expect(page.locator("#start")).to_have_value("2020-01-01")
            page.locator("#start").fill("")
            page.locator("#end").fill("")
            page.locator("#use-map").click()
            expect(page.locator("#start")).to_have_value("")
            expect(page.locator("#end")).to_have_value("")
            page.locator("#bbox").fill("29,-2,35,5")
            page.locator("#start").fill("2020-01-01")
            page.locator("#end").fill("2020-01-02")
            page.locator("#search").click()
            expect(page.locator(".result-card")).to_have_count(2)
            search_call = next(call for call in reversed(calls) if urlsplit(call["url"]).path == "/search")
            assert parse_qs(urlsplit(search_call["url"]).query) == {"bbox": ["29,-2,35,5"], "limit": ["25"], "collections": ["TEST"], "datetime": ["2020-01-01T00:00:00Z/2020-01-02T23:59:59.999999Z"]}
            coverage = page.locator("#map path.leaflet-interactive")
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
            assert not errors, errors
            browser.close()
        print("Browser fixture tests passed: protocol, UI, escaping, static catalogs, exports, recovery, responsive layout" + ("." if args.source else ", and site navigation."))
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
