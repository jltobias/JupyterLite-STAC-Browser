"""Execute tutorials in real JupyterLite, with fixture or live catalogs.

Requires a built _site, Playwright Chromium (or local Chrome), and public network
access to the Pyodide CDN. --fixtures runs the introductory notebook against
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
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-path", default="/JupyterLite-STAC-Browser")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fixtures", action="store_true", help="Run the intro with synthetic catalog responses")
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
            if args.fixtures:
                catalog = json.loads((ROOT / "tests/fixtures/catalog.json").read_text(encoding="utf-8"))
                items = copy.deepcopy(json.loads((ROOT / "tests/fixtures/items.json").read_text(encoding="utf-8")))
                items["features"] = [items["features"][0]]
                items["features"][0]["collection"] = "UGA"
                items["links"] = []

                def fixture(route):
                    path = urlsplit(route.request.url).path
                    if path in ("", "/"):
                        data = catalog
                    elif path == "/collections":
                        data = {"collections": [{"id": "UGA", "title": "Synthetic Uganda fixture"}], "links": []}
                    elif path == "/search":
                        data = items
                    else:
                        route.fulfill(status=404, body="{}", content_type="application/json")
                        return
                    route.fulfill(status=200, body=json.dumps(data), content_type="application/json",
                                  headers={"Access-Control-Allow-Origin": "*"})

                context.route("https://api.stac.worldpop.org/**", fixture)
                context.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
                context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
            page = context.new_page()
            page.set_default_timeout(120000)
            notebooks = [
                ("01_launch_map.ipynb", "browser runtime"),
                ("02_worldpop_search.ipynb", "Saved worldpop-items.geojson"),
                ("03_other_catalogs_and_export.ipynb", "Reproducible query:"),
            ]
            if args.fixtures:
                notebooks = notebooks[:1]
            elif args.copernicus:
                notebooks = notebooks[2:]
            for notebook, expected in notebooks:
                print(f"Opening {notebook}", flush=True)
                page.goto(f"{base}/lite/lab/index.html?path={notebook}", wait_until="domcontentloaded")
                page.locator(".jp-NotebookPanel:visible .jp-Notebook").wait_for()
                if args.copernicus:
                    editor = page.locator(".jp-NotebookPanel:visible .jp-CodeCell .cm-content").first
                    source = editor.inner_text().replace("PRESETS['earthsearch']", "PRESETS['copernicus']")
                    assert "PRESETS['copernicus']" in source, source
                    editor.click()
                    page.keyboard.press("ControlOrMeta+a")
                    page.keyboard.insert_text(source)
                    page.keyboard.press("Escape")
                print("Notebook editor loaded; executing cells", flush=True)
                page.get_by_text("Run", exact=True).first.click()
                page.get_by_text("Run All Cells", exact=True).click()
                deadline = time.monotonic() + 240
                while True:
                    errors = page.locator(".jp-NotebookPanel:visible .jp-OutputArea-error").all_text_contents()
                    assert not errors, f"{notebook}: {errors}"
                    outputs = page.locator(".jp-NotebookPanel:visible .jp-OutputArea-output").all_text_contents()
                    if any(expected in output for output in outputs):
                        break
                    if time.monotonic() > deadline:
                        page.screenshot(path=str(results / "lite-failure.png"))
                        raise AssertionError(f"Timed out executing {notebook}: {outputs}")
                    page.wait_for_timeout(1000)
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
                    frame.locator("#collection").select_option("UGA")
                    frame.locator("#search").click()
                    frame.locator(".result-card").first.wait_for()
                    print("Embedded map displayed " + ("synthetic fixture results" if args.fixtures else "live WorldPop results"), flush=True)
                page.screenshot(path=str(results / (notebook.replace(".ipynb", "") + ".png")))
                print(f"PASS {notebook}: {expected}", flush=True)
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
