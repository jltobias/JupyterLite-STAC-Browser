"""Synthetic bearer fixtures only: no live credential is acquired or printed."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import expect
from raster_clip_check import ATTACHMENT, BBOX, verify_crop, fulfill_raster


def check_copernicus_session(page, catalog, original):
    # Workers use the real clock; undo the earlier local-date regression clock.
    page.clock.set_system_time(datetime.now(timezone.utc))
    host = 'https://session-fixture.test'
    root = 'https://download.dataspace.copernicus.eu/odata/v1/Products(ccf70f3b-7b04-41f9-ade5-1443a085748e)'
    tiff_url = root + '/Nodes(product)/Nodes(source.tiff)/$value'
    nc_url = root + '/Nodes(product)/Nodes(original.nc)/$value'
    token = 'synthetic-browser-fixture-token'
    netcdf = b'CDF\x01\x00\xff\x80\x0aexact-original-NetCDF-bytes'
    item = copy.deepcopy(original)
    item.update(id='session-raster', collection='session-fixture', links=[{'rel': 'self', 'href': host + '/item.json'}])
    item['assets'] = {
        'tiff': {'href': tiff_url, 'type': 'image/tiff', 'roles': ['data']},
        'nc': {'href': nc_url, 'type': 'application/x-netcdf', 'roles': ['data']},
        'unsafe': {'href': root.replace('/odata/', '/erase/../odata/') + '/$value', 'roles': ['data']},
    }
    requests, pending, downloads, delayed_searches, public_pending, redirect_requests = [], [], [], [], [], []
    delay_search, delay_public = [False], [False]
    mode = ['range']

    def metadata(route):
        assert 'authorization' not in route.request.headers
        if route.request.url.split('?')[0].endswith('/public.tiff'):
            if delay_public[0]:
                public_pending.append(route)
            else:
                fulfill_raster(route)
            return
        if '/search' in route.request.url and delay_search[0]:
            delayed_searches.append(route)
            return
        data = {'type': 'FeatureCollection', 'features': [item], 'links': []} if '/search' in route.request.url else {
            **catalog, 'links': [{'rel': 'search', 'href': host + '/search'}]}
        route.fulfill(body=json.dumps(data), content_type='application/json', headers={'Access-Control-Allow-Origin': '*'})

    def protected(route):
        req = route.request
        assert req.url in (tiff_url, nc_url)
        assert req.headers.get('authorization') == 'Bearer ' + token or req.headers.get('authorization', '').startswith('Bearer e30.')
        assert 'cookie' not in req.headers
        requests.append({'url': req.url, 'range': req.headers.get('range')})
        if mode[0] == 'pending':
            pending.append(route)
            return
        headers = {'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'Content-Range, ETag', 'ETag': 'fixture'}
        if mode[0] == 'redirect':
            route.fulfill(status=302, body='', headers={**headers, 'Location': 'https://session-redirect.test/destination'})
            return
        if mode[0] in ('401', '403'):
            route.fulfill(status=int(mode[0]), body='Denied', headers=headers)
            return
        data = ATTACHMENT if req.url == tiff_url else netcdf
        if req.headers.get('range') and mode[0] != 'ignored':
            start, end = map(int, req.headers['range'].removeprefix('bytes=').split('-'))
            end = min(end, len(data) - 1)
            if mode[0] != 'hidden':
                headers['Content-Range'] = f'bytes {start}-{end}/{len(data)}'
            route.fulfill(status=206, body=data[start:end + 1], content_type='application/octet-stream', headers=headers)
        else:
            route.fulfill(body=data, content_type='application/octet-stream', headers=headers)

    page.context.route(host + '/**', metadata)
    page.context.route('https://download.dataspace.copernicus.eu/**', protected)
    def redirect_destination(route):
        redirect_requests.append(route.request.url)
        route.fulfill(body='Must not be reached', headers={'Access-Control-Allow-Origin': '*'})
    page.context.route('https://session-redirect.test/**', redirect_destination)
    record = lambda value: downloads.append(value)
    page.on('download', record)
    page.locator('#preset').select_option('custom')
    page.locator('#endpoint').fill(host)
    page.locator('#connect').click()
    expect(page.locator('#search')).to_be_enabled()
    page.locator('#spatial-mode').select_option('none')
    page.locator('#search').click()
    page.locator('.result-card').click()
    page.locator('#bbox').fill(','.join(map(str, BBOX)))
    page.locator('#bbox').press('Tab')
    assert not requests
    page.locator('.copernicus-connection').evaluate('(node) => { node.open = true; }')

    def load(value=token):
        page.locator('#copernicus-token').fill(value)
        page.locator('#copernicus-load').click()
        expect(page.locator('#copernicus-token')).to_have_value('')
        expect(page.locator('#copernicus-status')).to_contain_text('Token loaded')

    load()
    expect(page.locator('#copernicus-status')).to_contain_text('not verified')
    assert not requests
    expect(page.locator('.asset-check')).to_have_count(2)
    expect(page.locator('.asset-original')).to_have_count(2)
    expect(page.locator('.asset-clip')).to_have_count(1)
    expect(page.locator('.clip-unavailable').filter(has_text='NetCDF')).to_have_count(1)
    expect(page.locator('.scope-unavailable')).to_contain_text('outside the permitted Copernicus download scope')
    expect(page.locator('.session-download-help')).to_contain_text('Your token is loaded')
    for state, message in [('401', 'HTTP 401'), ('403', 'HTTP 403'), ('ignored', 'ignored HTTP Range'), ('hidden', 'exactly 16 bytes')]:
        mode[0] = state
        page.locator('.asset-check').first.click()
        expect(page.locator('.protected-status').first).to_contain_text(message)
    expect(page.locator('#copernicus-status')).to_contain_text('not verified')
    expect(page.locator('.protected-status').first).to_contain_text('byte offsets cannot be independently verified')
    assert all(request['range'] == 'bytes=0-15' for request in requests)
    mode[0] = 'range'
    page.locator('.asset-check').first.click()
    expect(page.locator('.protected-status').first).to_contain_text('verified offsets 0–15')
    mode[0] = 'redirect'
    page.locator('.asset-check').first.click()
    expect(page.locator('.protected-status').first).to_contain_text('redirects are blocked')
    assert not redirect_requests

    # Speed up only the request timer, keeping the token valid during an idle timeout.
    mode[0] = 'pending'
    page.evaluate('''() => {
      window.normalTimeout = window.setTimeout;
      window.setTimeout = (fn, ms, ...args) => window.normalTimeout(fn, ms === 20000 ? 30 : ms, ...args);
    }''')
    before = len(downloads)
    page.locator('.asset-check').first.click()
    expect(page.locator('.protected-status').first).to_contain_text('timed out')
    expect(page.locator('.asset-check').first).to_be_enabled()
    expect(page.locator('#copernicus-status')).to_contain_text('Token loaded')
    assert len(downloads) == before
    page.evaluate('() => { window.setTimeout = window.normalTimeout; }')
    while pending:
        try:
            pending.pop().abort()
        except Exception:
            pass

    # Real worker + bundled GeoTIFF.js/proj4; independent rasterio pixel check.
    mode[0] = 'range'
    with page.expect_download() as crop:
        page.locator('.asset-clip').click()
    output = Path(crop.value.path()).read_bytes()
    verify_crop(ATTACHMENT, output)
    assert token.encode() not in output
    with page.expect_download() as provenance:
        page.get_by_role('button', name='Download crop provenance (.json)').click()
    assert token not in Path(provenance.value.path()).read_text()

    # Unsupported picker -> bounded Blob path; the NC bytes and suffix survive.
    page.evaluate('window.showSaveFilePicker = undefined')
    load()
    with page.expect_download() as nc:
        page.locator('.asset-original').nth(1).click()
    assert nc.value.suggested_filename == 'original.nc'
    assert Path(nc.value.path()).read_bytes() == netcdf

    # A real browser FileSystemFileHandle exercises writable streaming and close.
    page.evaluate('''() => {
      window.pickerCalls = 0;
      window.showSaveFilePicker = async options => {
        window.pickerCalls++;
        window.pickerActivated = navigator.userActivation.isActive;
        const root = await navigator.storage.getDirectory();
        window.testHandle = await root.getFileHandle(options.suggestedName, {create: true});
        return window.testHandle;
      };
    }''')
    load()
    page.locator('.asset-original').first.click()
    expect(page.locator('.protected-status').first).to_contain_text('Saved original file')
    assert page.evaluate('window.pickerCalls === 1 && window.pickerActivated')
    assert bytes(page.evaluate('async () => Array.from(new Uint8Array(await (await window.testHandle.getFile()).arrayBuffer()))')) == ATTACHMENT
    assert len(downloads) == 3

    # Native stream close is finalization: disable Cancel and report a successful close.
    page.evaluate('''() => {
      window.showSaveFilePicker = async () => ({createWritable: async () => new WritableStream({
        write() {}, close() { return new Promise(resolve => { window.finishClose = resolve; }); }
      }).getWriter()});
    }''')
    load()
    page.locator('.asset-original').first.click()
    expect(page.locator('.protected-status').first).to_contain_text('Finishing save')
    expect(page.locator('.transfer-cancel').first).to_be_disabled()
    page.evaluate('window.finishClose()')
    expect(page.locator('.protected-status').first).to_contain_text('Saved original file')

    # The explicit fallback is usable when a browser exposes but blocks a picker.
    page.evaluate("() => { window.showSaveFilePicker = async () => { throw new DOMException('Unavailable', 'SecurityError'); }; }")
    before = len(requests)
    page.locator('.asset-original').first.click()
    expect(page.locator('.protected-status').first).to_contain_text('File picker unavailable')
    assert len(requests) == before
    with page.expect_download() as fallback:
        page.locator('.asset-original-fallback').first.click()
    assert Path(fallback.value.path()).read_bytes() == ATTACHMENT

    # A late native-picker result cannot create a writable or issue a fetch.
    page.evaluate('''() => {
      window.createdLate = false;
      window.showSaveFilePicker = () => new Promise(resolve => {
        window.releasePicker = () => resolve({createWritable: async () => { window.createdLate = true; throw Error(); }});
      });
    }''')
    before = len(requests)
    page.locator('.asset-original').first.click()
    page.locator('.result-card').click()
    page.evaluate('window.releasePicker()')
    page.wait_for_timeout(100)
    assert not page.evaluate('window.createdLate') and len(requests) == before
    expect(page.locator('.protected-status').first).to_be_empty()

    # A transfer started from old controls while search awaits must be canceled at commit.
    page.evaluate('window.showSaveFilePicker = undefined')
    load()
    before = len(downloads)
    delay_search[0], mode[0] = True, 'pending'
    page.locator('#search').click()
    expect(page.locator('#search')).to_be_disabled()
    page.locator('.asset-original').first.click()
    page.wait_for_timeout(100)
    assert delayed_searches and pending
    item['id'] = 'replacement-session-raster'
    delay_search[0] = False
    delayed_searches.pop().fulfill(body=json.dumps({'type': 'FeatureCollection', 'features': [item], 'links': []}), content_type='application/json', headers={'Access-Control-Allow-Origin': '*'})
    expect(page.locator('#search')).to_be_enabled()
    page.locator('.result-card').click()
    while pending:
        try:
            pending.pop().fulfill(body=ATTACHMENT)
        except Exception:
            pass
    page.wait_for_timeout(100)
    assert len(downloads) == before
    expect(page.locator('.protected-status').first).to_be_empty()
    mode[0] = 'range'

    # Mixed-item public crops keep their exact DOM nodes and worker on token load/clear.
    item['assets']['public'] = {'href': host + '/public.tiff?note=download.dataspace.copernicus.eu', 'type': 'image/tiff', 'roles': ['data'], 'title': 'Public fixture'}
    page.locator('#search').click()
    expect(page.locator('#search')).to_be_enabled()
    page.locator('.result-card').click()
    public_clip = page.locator('.download-assets li').filter(has_text='Public fixture').locator('.asset-clip')
    public_clip.evaluate('(node) => { window.publicCropNode = node; }')
    delay_public[0] = True
    with page.expect_request(lambda request: request.url == item['assets']['public']['href']):
        with page.expect_event('worker') as started:
            public_clip.click()
    worker = started.value
    page.wait_for_timeout(100)
    assert public_pending
    load()
    page.locator('#copernicus-clear').click()
    assert page.evaluate('window.publicCropNode.isConnected') and worker in page.workers
    delay_public[0] = False
    with page.expect_download() as public_crop:
        for route in public_pending:
            fulfill_raster(route)
    public_pending.clear()
    verify_crop(ATTACHMENT, Path(public_crop.value.path()).read_bytes())
    expect(page.locator('.download-assets li').filter(has_text='Public fixture').locator('.crop-status')).to_contain_text('Saved')
    del item['assets']['public']
    page.locator('#search').click()
    expect(page.locator('#search')).to_be_enabled()
    page.locator('.result-card').click()
    load()

    # No token can appear in exported metadata/query, DOM text, cookies or storage.
    for selector in ['.metadata-download', '#export-geojson', '#export-query']:
        with page.expect_download() as exported:
            page.locator(selector).click()
        assert token not in Path(exported.value.path()).read_text()
    assert token not in page.locator('body').inner_text()
    assert page.evaluate('JSON.stringify(localStorage) + JSON.stringify(sessionStorage) + document.cookie').find(token) == -1

    # Cancellation of real workers under each session and selection lifecycle event.
    baseline = len(downloads)
    for action in ['clear', 'replace', 'expiry', 'pagehide', 'cancel', 'bbox', 'item', 'catalog']:
        mode[0] = 'pending'
        if action == 'expiry':
            value = page.evaluate("'e30.' + btoa(JSON.stringify({exp: (Date.now() + 1600) / 1000})) + '.synthetic'")
            load(value)
        else:
            load()
        with page.expect_event('worker') as started:
            page.locator('.asset-clip').click()
        worker = started.value
        page.wait_for_timeout(100)
        with worker.expect_event('close', timeout=6000):
            if action == 'clear':
                page.locator('#copernicus-clear').click()
            elif action == 'replace':
                load()
            elif action == 'expiry':
                expect(page.locator('#copernicus-status')).to_contain_text('Session expired', timeout=6000)
            elif action == 'pagehide':
                page.locator('#copernicus-token').fill('unsubmitted')
                page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
                expect(page.locator('#copernicus-token')).to_have_value('')
            elif action == 'cancel':
                page.locator('.crop-cancel').click()
            elif action == 'bbox':
                page.locator('#bbox').fill('10.18,19.39,10.45,19.78')
            elif action == 'catalog':
                page.locator('#preset').select_option('copernicus')
            else:
                page.locator('.result-card').click()
        while pending:
            try:
                pending.pop().fulfill(status=206, body=ATTACHMENT[:16], headers={'Content-Range': f'bytes 0-15/{len(ATTACHMENT)}'})
            except Exception:
                pass  # Worker termination may already have canceled the route.
        page.wait_for_timeout(50)
        assert len(downloads) == baseline

    # Pending original fetch resolves after clear: suppress Blob and stale status.
    page.evaluate('window.showSaveFilePicker = undefined')
    load()
    page.locator('.asset-original').first.click()
    page.wait_for_timeout(100)
    page.locator('#copernicus-clear').click()
    while pending:
        try:
            pending.pop().fulfill(body=ATTACHMENT)
        except Exception:
            pass
    page.wait_for_timeout(100)
    assert len(downloads) == baseline
    expect(page.locator('.asset-check')).to_have_count(0)
    expect(page.locator('#copernicus-token')).to_have_value('')
    assert token not in page.content()
    # A real navigation discards module memory; load/select alone sent no requests.
    mode[0] = 'range'
    load()
    viewport = page.viewport_size
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    expect(page.locator('.asset-check').first).to_be_visible()
    page.set_viewport_size(viewport)
    before = len(requests)
    page.reload()
    expect(page.locator('#copernicus-status')).to_contain_text('No token loaded')
    expect(page.locator('#copernicus-token')).to_have_value('')
    expect(page.locator('.asset-check, .asset-original')).to_have_count(0)
    assert len(requests) == before
    page.context.unroute(host + '/**', metadata)
    page.context.unroute('https://download.dataspace.copernicus.eu/**', protected)
    page.context.unroute('https://session-redirect.test/**', redirect_destination)
    page.remove_listener('download', record)
    print('Copernicus session fixtures passed: exact original bytes, real worker crop, OPFS streaming, scope, exports, expiry and stale-work cancellation. Live authorized access is unverified.', flush=True)


if __name__ == '__main__':
    # Focused source regression runner; the complete suite calls the same function.
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from playwright.sync_api import sync_playwright
    root_dir = Path(__file__).resolve().parents[1]
    catalog = json.loads((root_dir / 'tests/fixtures/catalog.json').read_text())
    items = json.loads((root_dir / 'tests/fixtures/items.json').read_text())
    class Handler(SimpleHTTPRequestHandler):
        def translate_path(self, path):
            return super().translate_path(path.replace('/explorer/', '/web/', 1))
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(root_dir)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
            browser = playwright.chromium.launch(headless=True, **({'executable_path': str(chrome)} if chrome.exists() else {}))
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('https://api.stac.worldpop.org/**', lambda route: route.fulfill(body=json.dumps({'collections': [], 'links': []} if '/collections' in route.request.url else catalog), content_type='application/json', headers={'Access-Control-Allow-Origin': '*'}))
            page.goto(f'http://127.0.0.1:{server.server_port}/explorer/')
            expect(page.locator('#connect')).to_be_enabled()
            check_copernicus_session(page, catalog, items['features'][0])
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
