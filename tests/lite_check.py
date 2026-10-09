"""Execute tutorials in real JupyterLite, with fixture or live catalogs.

Requires a built _site, Playwright Chromium (or local Chrome), and public network
access to the Pyodide CDN. --fixtures runs the tutorials and spatial replay against
synthetic local responses in CI; the default runs all tutorials with live APIs.
"""
import argparse
import copy
import json
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit, parse_qs

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-path", default="/JupyterLite-STAC-Browser")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fixtures", action="store_true", help="Run tutorials and spatial replay with synthetic catalog responses")
    mode.add_argument("--copernicus", action="store_true", help="Run notebook 03 with the documented Copernicus substitution against the live API")
    parser.add_argument("--site-url", help="Test an already deployed site instead of the local build")
    args = parser.parse_args()
    prefix = args.base_path.rstrip("/")

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if prefix and self.path.startswith(prefix + "/"):
                self.path = self.path[len(prefix):]
            super().do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=ROOT / "_site"))
    Thread(target=server.serve_forever, daemon=True).start()
    base = args.site_url.rstrip("/") if args.site_url else f"http://127.0.0.1:{server.server_port}{prefix}"
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, **({"executable_path": str(chrome)} if chrome.exists() else {}))
            context = browser.new_context(viewport={"width": 1440, "height": 1080})
            searches = []
            search_requests = []
            context.on('request', lambda request: search_requests.append(request.url)
                       if urlsplit(request.url).path.rstrip('/').endswith('/search') else None)
            if args.fixtures:
                catalog = json.loads((ROOT / "tests/fixtures/catalog.json").read_text(encoding="utf-8"))
                items = copy.deepcopy(json.loads((ROOT / "tests/fixtures/items.json").read_text(encoding="utf-8")))
                items["features"] = [items["features"][0]]
                items["features"][0]["collection"] = "UGA"
                items["links"] = []

                def fixture(route):
                    path = urlsplit(route.request.url).path
                    if path.startswith('/v1'):
                        path = path[3:]
                    if path in ("", "/"):
                        data = catalog
                    elif path == "/collections":
                        data = {"collections": [{"id": "UGA", "title": "Synthetic Uganda fixture"}], "links": []}
                    elif path == "/search":
                        data = items
                        query = parse_qs(urlsplit(route.request.url).query)
                        searches.append(query)
                        assert not ('bbox' in query and 'intersects' in query)
                    else:
                        route.fulfill(status=404, body="{}", content_type="application/json")
                        return
                    route.fulfill(status=200, body=json.dumps(data), content_type="application/json",
                                  headers={"Access-Control-Allow-Origin": "*"})

                context.route("https://api.stac.worldpop.org/**", fixture)
                context.route("https://earth-search.aws.element84.com/**", fixture)
                context.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
                context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
            page = context.new_page()
            page.set_default_timeout(120000)
            notebooks = [
                ("01_launch_map.ipynb", "browser runtime"),
                ("02_worldpop_search.ipynb", "Saved worldpop-items.geojson"),
                ("03_other_catalogs_and_export.ipynb", "Reproducible query:"),
            ]
            if args.copernicus:
                notebooks = notebooks[2:]
            for notebook, expected in notebooks:
                searches.clear()
                print(f"Opening {notebook}", flush=True)
                document = json.loads((ROOT / '_site/lite/files' / notebook).read_text(encoding='utf-8'))
                heading = ''.join(document['cells'][0]['source']).splitlines()[0].removeprefix('# ')
                if args.fixtures and notebook.startswith('03'):
                    # Identify and edit the exact built source before Lite loads it.
                    # DOM cell positions and text are incomplete under virtualization.
                    replay_cell = next(cell for cell in document['cells']
                                       if cell['cell_type'] == 'code' and 'async def replay_saved' in ''.join(cell['source']))
                    replay_cell['source'] = ''.join(replay_cell['source']) + '''

from copy import deepcopy
for mode in ['bbox', 'polygon', 'none']:
    sample = deepcopy(saved)
    sample['query'].pop('bbox', None)
    sample['query'].pop('intersects', None)
    if mode == 'bbox':
        sample['query']['bbox'] = [30, -1, 33, 3]
    elif mode == 'polygon':
        sample['query']['intersects'] = {'type': 'Polygon', 'coordinates': [[[30, -1], [33, -1], [32, 3], [30, -1]]]}
    replay_items = await replay_saved(sample)
    assert replay_items, mode
print('Spatial replay passed: bbox, polygon, none')
'''
                    expected = 'Spatial replay passed: bbox, polygon, none'
                if args.copernicus:
                    connection_cell = next(cell for cell in document['cells'] if cell['cell_type'] == 'code')
                    connection_cell['source'] = ''.join(connection_cell['source']).replace("PRESETS['earthsearch']", "PRESETS['copernicus']")
                    assert "PRESETS['copernicus']" in connection_cell['source']
                if notebook.startswith('03') and (args.fixtures or args.copernicus):
                    context.route(f"**/lite/files/{notebook}*", lambda route: route.fulfill(
                        body=json.dumps(document), content_type='application/json'))
                page.goto(f"{base}/lite/lab/index.html?path={notebook}", wait_until="domcontentloaded")
                page.locator(".jp-NotebookPanel:visible .jp-Notebook").wait_for()
                expect(page.locator('.jp-NotebookPanel:visible .jp-Notebook')).to_contain_text(heading)
                print("Notebook editor loaded; executing cells", flush=True)
                page.get_by_text("Run", exact=True).first.click()
                page.get_by_text("Run All Cells", exact=True).click()
                deadline = time.monotonic() + 240
                while True:
                    errors = page.locator(".jp-NotebookPanel:visible .jp-OutputArea-error").all_text_contents()
                    assert not errors, f"{notebook}: {errors}"
                    outputs = page.locator(".jp-NotebookPanel:visible .jp-OutputArea-output").all_text_contents()
                    assert not any('Traceback (most recent call last)' in output for output in outputs), (notebook, outputs)
                    if any(expected in output for output in outputs):
                        break
                    if time.monotonic() > deadline:
                        page.screenshot(path=str(results / "lite-failure.png"))
                        raise AssertionError(f"Timed out executing {notebook}: {outputs}")
                    page.wait_for_timeout(1000)
                if args.fixtures and notebook.startswith('03'):
                    assert len(searches) == 4, searches
                    for query, mode in zip(searches[1:], ['bbox', 'polygon', 'none']):
                        assert ('bbox' in query) == (mode == 'bbox'), query
                        assert ('intersects' in query) == (mode == 'polygon'), query
                        assert query['collections'] == ['sentinel-2-l2a'], query
                        assert query['limit'] == ['3'], query
                        assert query['datetime'][0].startswith('2024-06-01T00:00:00Z/2024-06-15'), query
                        if mode == 'bbox':
                            assert [float(x) for x in query['bbox'][0].split(',')] == [30, -1, 33, 3]
                        elif mode == 'polygon':
                            assert json.loads(query['intersects'][0]) == {'type': 'Polygon', 'coordinates': [[[30, -1], [33, -1], [32, 3], [30, -1]]]}
                if notebook.startswith('03'):
                    snapshot = json.loads((ROOT / 'web/public-catalogs.json').read_text(encoding='utf-8'))
                    assert (ROOT / '_site/lite/files/public-catalogs.json').read_bytes() == (ROOT / 'web/public-catalogs.json').read_bytes()
                    assert any(f"Directory: {len(snapshot['catalogs'])} public listings; fetched {snapshot['fetched_at']}" in output for output in outputs), outputs
                    assert any(snapshot['source'] in output and snapshot['api'] in output for output in outputs), outputs
                if args.copernicus:
                    assert any("Source root: https://stac.dataspace.copernicus.eu/v1" in output for output in outputs), outputs
                    assert any("Saved earthsearch-items.geojson" in output for output in outputs), outputs
                    print("Copernicus metadata search and exports passed in Pyodide", flush=True)
                if notebook.startswith("01"):
                    print("Frame URLs:", [f.url for f in page.frames], flush=True)
                    frame = page.frame_locator('iframe[src$="/explorer/"]')
                    try:
                        expect(frame.locator("#catalog-summary")).to_contain_text("collections loaded", timeout=30000)
                    except AssertionError:
                        print("Failed frame URLs:", [f.url for f in page.frames], flush=True)
                        print("Notebook outputs:", page.locator(".jp-OutputArea").all_text_contents(), flush=True)
                        page.screenshot(path=str(results / "lite-failure.png"))
                        raise
                    frame.locator('#preset').select_option('directory')
                    expect(frame.locator('#directory-catalog')).to_be_enabled()
                    snapshot = json.loads((ROOT / 'web/public-catalogs.json').read_text(encoding='utf-8'))
                    expect(frame.locator('#directory-count')).to_contain_text(f"{len(snapshot['catalogs'])} public listings")
                    frame.locator('#directory-filter').fill('earth')
                    expect(frame.locator('#directory-catalog option')).not_to_have_count(1)
                    frame.locator('#preset').select_option('worldpop')
                    frame.locator("#collection").select_option("UGA")
                    expect(frame.locator('#map .study-area')).to_have_count(1)
                    frame.locator('#polygon-area').click()
                    expect(frame.locator('#map .marker-icon-middle')).to_have_count(4)
                    frame.locator('#zoom-area').click()
                    frame.locator('#map .marker-icon-middle').first.click()
                    print('Iframe edit status:', frame.locator('#status').inner_text(), flush=True)
                    expect(frame.locator('#map .marker-icon-middle')).to_have_count(5)
                    frame.locator('#spatial-mode').select_option('polygon')
                    frame.locator("#search").click()
                    frame.locator(".result-card").first.wait_for()
                    frame.locator('#spatial-mode').select_option('none')
                    frame.locator('#search').click()
                    expect(frame.locator('#search')).to_be_enabled()
                    expect(frame.locator('#edit-area')).to_have_attribute('aria-pressed', 'false')
                    count_before_resume = len(search_requests)
                    bbox_before_resume = frame.locator('#bbox').input_value()
                    frame.locator('#spatial-mode').select_option('bbox')
                    expect(frame.locator('#edit-area')).to_have_attribute('aria-pressed', 'true')
                    expect(frame.locator('#area-summary')).to_contain_text('Rectangle')
                    expect(frame.locator('#map .marker-icon-middle')).to_have_count(0)
                    expect(frame.locator('#map .marker-icon')).to_have_count(4)
                    expect(frame.locator('#bbox')).to_have_value(bbox_before_resume)
                    assert len(search_requests) == count_before_resume, 'Resuming iframe editing must not search'
                    print("Embedded map displayed " + ("synthetic fixture results" if args.fixtures else "live WorldPop results"), flush=True)
                page.screenshot(path=str(results / (notebook.replace(".ipynb", "") + ".png")))
                print(f"PASS {notebook}: {expected}", flush=True)
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
