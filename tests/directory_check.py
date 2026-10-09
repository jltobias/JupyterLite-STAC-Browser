"""Real browser interactions with deterministic directory/provider fixtures."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
API = "https://stacindex.org/api/catalogs"


def check_deafrica(page, calls):
    endpoint = "https://explorer.digitalearth.africa/stac/"
    def fixture(route):
        request = route.request
        calls.append({"url": request.url, "method": request.method, "body": request.post_data})
        path = urlsplit(request.url).path
        if path == "/stac/":
            data = {"type": "Catalog", "id": "deafrica-fixture", "stac_version": "1.1.0", "links": [
                {"rel": "data", "href": "./collections"}, {"rel": "search", "href": "./search"}]}
        elif path == "/stac/collections":
            data = {"collections": [{"id": "s2_l2a", "title": "Sentinel-2 L2A"}], "links": []}
        elif path == "/stac/search":
            data = {"type": "FeatureCollection", "features": [], "links": []}
        else:
            raise AssertionError(request.url)
        route.fulfill(body=json.dumps(data), content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})
    page.route("https://explorer.digitalearth.africa/**", fixture)
    before = len(calls)
    page.locator("#preset").select_option("deafrica")
    expect(page.locator("#endpoint")).to_have_value(endpoint)
    assert len(calls) == before
    page.locator("#connect").click()
    expect(page.locator("#collection option")).to_have_count(2)
    page.locator("#collection").select_option("s2_l2a")
    page.locator("#bbox").fill("45,-20.1,47,-19.8")
    page.locator("#start").fill("2020-01-01")
    page.locator("#end").fill("2020-01-31")
    page.locator("#limit").select_option("10")
    page.locator("#search").click()
    expect(page.locator("#search")).to_be_enabled()
    assert calls[before]["url"] == endpoint
    assert parse_qs(urlsplit(calls[-1]["url"]).query) == {
        "collections": ["s2_l2a"], "bbox": ["45,-20.1,47,-19.8"], "limit": ["10"],
        "datetime": ["2020-01-01T00:00:00Z/2020-01-31T23:59:59.999999Z"]}


def check_directory(page, calls, pending_connections, catalog):
    bundled = json.loads((ROOT / "web/public-catalogs.json").read_text(encoding="utf-8"))
    page.locator("#preset").select_option("directory")
    expect(page.locator("#directory-catalog")).to_be_enabled()
    expect(page.locator("#directory-count")).to_have_text(f"{len(bundled['catalogs'])} of {len(bundled['catalogs'])} public listings")
    values = page.locator("#directory-catalog option").evaluate_all("els => els.slice(1).map(e=>JSON.parse(e.value)[0])")
    assert values == [row["id"] for row in bundled["catalogs"]]
    assert page.locator("#directory-date").inner_text().endswith(bundled["fetched_at"])
    original_calls = len(calls)
    row = bundled["catalogs"][0]
    page.locator("#directory-catalog").select_option(json.dumps([row["id"], row["url"]], separators=(",", ":")))
    expect(page.locator("#endpoint")).to_have_value(row["url"])
    page.locator("#directory-filter").fill("a filter that matches nothing")
    expect(page.locator("#directory-count")).to_contain_text("selected endpoint retained")
    expect(page.locator("#endpoint")).to_have_value(row["url"])
    assert len(calls) == original_calls
    for row in bundled["catalogs"]:
        if row["url"].startswith("https://"):
            continue
        page.locator("#directory-filter").fill(row["title"])
        page.locator("#directory-catalog").select_option(json.dumps([row["id"], row["url"]], separators=(",", ":")))
        expect(page.locator("#connect")).to_be_disabled()
        expect(page.locator("#directory-problem")).to_contain_text("has not been changed")
        expect(page.locator("#directory-source")).to_have_attribute("href", "https://stacindex.org/catalogs/" + row["slug"])
    assert len(calls) == original_calls
    base_row = {"id": 1, "slug": "alpha-api", "title": "Alpha API", "url": "https://fixture.test/?advertised=keep", "access": "public", "isApi": True}
    rows = [base_row,
            {**base_row, "id": 2, "slug": "static", "title": "Beta static", "url": "https://fixture.test/static.json", "isApi": False},
            {**base_row, "id": 3, "slug": "delayed", "title": "Gamma delayed", "url": "https://fixture.test/delayed"},
            {**base_row, "id": 4, "slug": "<script>", "title": "<img src=x onerror=alert(1)>", "url": "javascript:alert(1)"},
            {**base_row, "id": 5, "title": "Private hidden", "access": "private"}]
    refreshes = []
    page.route(API, lambda route: refreshes.append(route))
    page.locator("#directory-filter").fill("")
    selected = page.locator("#endpoint").input_value()
    summary = page.locator("#catalog-summary").inner_text()
    original_options = page.locator("#directory-catalog option").evaluate_all("els => els.map(e=>e.value)")
    def exercise_retained_directory():
        assert page.locator("#directory-catalog option").evaluate_all("els => els.map(e=>e.value)") == original_options
        retained_row = next(row for row in bundled["catalogs"] if row["url"] != page.locator("#endpoint").input_value() and row["url"].startswith("https://"))
        before = len(calls)
        page.locator("#directory-filter").fill(retained_row["title"])
        page.locator("#directory-catalog").select_option(json.dumps([retained_row["id"], retained_row["url"]], separators=(",", ":")))
        expect(page.locator("#endpoint")).to_have_value(retained_row["url"])
        expect(page.locator("#connect")).to_be_enabled()
        page.locator("#directory-filter").fill("")
        assert len(calls) == before
        expect(page.locator("#catalog-summary")).to_have_text(summary)
    malformed_slug = json.dumps([{**base_row, "slug": "bad\ud800slug"}])
    for response, message in [("<html>bad", "non-JSON"), ("{}", "array"), ("[null]", "Invalid directory"), (malformed_slug, "Invalid public")]:
        page.locator("#directory-refresh").click()
        expect(page.locator("#directory-filter")).to_be_disabled()
        expect(page.locator("#directory-catalog")).to_be_disabled()
        expect(page.locator("#connect")).to_be_disabled()
        refreshes.pop().fulfill(body=response, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})
        expect(page.locator("#directory-status")).to_contain_text(message)
        expect(page.locator("#directory-refresh")).to_be_enabled()
        expect(page.locator("#endpoint")).to_have_value(selected)
        expect(page.locator("#catalog-summary")).to_have_text(summary)
        exercise_retained_directory()
        selected = page.locator("#endpoint").input_value()
    # The existing fetch timeout is used unchanged; fast-forward its real UI request.
    page.locator("#directory-refresh").click()
    page.clock.fast_forward(21000)
    expect(page.locator("#directory-status")).to_contain_text("timed out")
    refreshes.pop().abort()
    expect(page.locator("#endpoint")).to_have_value(selected)
    exercise_retained_directory()
    selected = page.locator("#endpoint").input_value()
    def refresh(data):
        page.locator("#directory-refresh").click()
        refreshes.pop().fulfill(body=json.dumps(data), content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})
        expect(page.locator("#directory-status")).to_contain_text("Directory refreshed")
        expect(page.locator("#directory-catalog")).to_be_enabled()
    refresh(rows)
    expect(page.locator("#endpoint")).to_have_value(selected)
    expect(page.locator("#directory-count")).to_contain_text("4 of 4")
    assert "Private hidden" not in page.locator("#directory-catalog").inner_text()
    def choose(row):
        page.locator("#directory-filter").fill("")
        page.locator("#directory-catalog").select_option(json.dumps([row["id"], row["url"]], separators=(",", ":")))
    choose(rows[3])
    expect(page.locator("#connect")).to_be_disabled()
    assert page.locator("#directory-panel img, #directory-panel script").count() == 0
    assert page.locator("#directory-source").get_attribute("href").endswith("%3Cscript%3E")
    choose(base_row)
    before = len(calls)
    expect(page.locator("#endpoint")).to_have_value(base_row["url"])
    page.locator("#directory-filter").fill("Alpha")
    page.locator("#directory-filter").press("Enter")
    assert len(calls) == before
    page.locator("#connect").click()
    expect(page.locator("#search")).to_be_enabled()
    assert calls[before]["url"] == base_row["url"]
    updated_row = {**base_row, "title": "Updated Alpha listing", "slug": "updated-alpha", "isApi": False}
    refresh([updated_row])
    expect(page.locator("#directory-catalog option:checked")).to_have_text("Updated Alpha listing · Static catalog")
    expect(page.locator("#directory-type")).to_have_text("Static catalog listing")
    expect(page.locator("#directory-source")).to_have_attribute("href", "https://stacindex.org/catalogs/updated-alpha")
    expect(page.locator("#endpoint")).to_have_value(base_row["url"])
    refresh([{**base_row, "url": "https://fixture.test/changed"}])
    expect(page.locator("#endpoint")).to_have_value(base_row["url"])
    expect(page.locator("#directory-count")).to_contain_text("selected endpoint retained")
    expect(page.locator("#search")).to_be_enabled()
    expect(page.locator("#directory-type")).to_have_text("Static catalog listing")
    expect(page.locator("#directory-source")).to_have_attribute("href", "https://stacindex.org/catalogs/updated-alpha")
    # Browser fetch follows a genuine 302 to a loopback-served fixture. Playwright
    # does not route redirected requests, so serve the destination without TLS bypass.
    redirect_row = {**base_row, "id": 6, "title": "Redirected API", "url": "https://fixture.test/redirect?advertised=keep"}
    redirects = []
    class RedirectTarget(BaseHTTPRequestHandler):
        def do_GET(self):
            redirects.append(self.path)
            body = json.dumps({**catalog, "links": [
                {"rel": "data", "href": "https://fixture.test/collections"},
                {"rel": "search", "href": "https://fixture.test/search"}]}).encode()
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    redirect_server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectTarget)
    Thread(target=redirect_server.serve_forever, daemon=True).start()
    def redirect_fixture(route):
        redirects.append(route.request.url)
        route.fulfill(status=302, headers={"Access-Control-Allow-Origin": "*",
                      "Location": f"http://127.0.0.1:{redirect_server.server_port}/root.json"}, body="")
    page.route(redirect_row["url"], redirect_fixture)
    try:
        refresh([redirect_row])
        choose(redirect_row)
        page.locator("#connect").click()
        expect(page.locator("#search")).to_be_enabled()
        expect(page.locator("#collection option")).to_have_count(3)
        expect(page.locator("#endpoint")).to_have_value(redirect_row["url"])
        assert redirects == [redirect_row["url"], "/root.json"]
        assert calls[-1]["url"] == "https://fixture.test/collections"
    finally:
        page.unroute(redirect_row["url"], redirect_fixture)
        redirect_server.shutdown()
        redirect_server.server_close()
    refresh(rows)
    choose(rows[1])
    before = len(calls)
    page.locator("#connect").click()
    expect(page.locator("#status")).to_contain_text("Static catalog connected")
    assert calls[before]["url"] == rows[1]["url"]
    page.locator("#catalog-links button").first.click()
    expect(page.locator("#status")).to_contain_text("Loaded one static STAC Item")
    choose(rows[2])
    page.locator("#connect").click()
    for control in ["#preset", "#endpoint", "#directory-catalog", "#directory-filter", "#directory-refresh"]:
        expect(page.locator(control)).to_be_disabled()
    pending_connections.pop().fulfill(body=json.dumps(catalog), content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})
    expect(page.locator("#search")).to_be_enabled()
    expect(page.locator("#endpoint")).to_have_value(rows[2]["url"])
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(ROOT / "test-results/directory-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.screenshot(path=str(ROOT / "test-results/directory-desktop.png"), full_page=True)
    # Initial load is serialized with refresh, without blocking featured/custom use.
    waiting = []
    page.route("**/public-catalogs.json", lambda route: waiting.append(route))
    page.reload()
    expect(page.locator("#search")).to_be_enabled()
    page.locator("#preset").select_option("directory")
    expect(page.locator("#directory-refresh")).to_be_disabled()
    waiting.pop().fulfill(body="{}", content_type="application/json")
    expect(page.locator("#directory-status")).to_contain_text("Bundled directory unavailable")
    expect(page.locator("#directory-count")).to_have_text("No directory loaded.")
    page.locator("#preset").select_option("custom")
    expect(page.locator("#endpoint")).to_be_editable()
    expect(page.locator("#connect")).to_be_enabled()
    page.unroute("**/public-catalogs.json")
    page.unroute(API)
    page.reload()
    expect(page.locator("#search")).to_be_enabled()
    page.locator("#preset").select_option("directory")
    expect(page.locator("#directory-catalog")).to_be_enabled()
