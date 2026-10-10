"""Selected dataset access: real attachment download, alternatives, and fallbacks."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect

ATTACHMENT = b'II\x2a\x00Synthetic attachment fixture, not a real raster.'


def check_downloads(page, catalog, items):
    host = 'https://download-fixture.test'
    item = copy.deepcopy(items['features'][0])
    item['id'] = 'download-fixture'
    item['properties']['title'] = 'Dataset with several files'
    item['links'] = [{'rel': 'self', 'href': host + '/items/selected.json'},
                     {'rel': 'about', 'href': host + '/provider', 'title': 'Provider access'}]
    item['assets'] = {
        'preview': {'href': './preview.png', 'roles': ['thumbnail'], 'title': 'Preview'},
        'raster': {'href': './data.tif', 'roles': ['data'], 'title': 'Population raster', 'type': 'image/tiff'},
        'second': {'href': 's3://fixture/second.tif', 'roles': ['data'], 'title': 'Download - Second raster',
                   'alternate': {'https': {'href': ' '}, 'public': {'href': host + '/second.tif'}}},
        'blank_alternate': {'href': 's3://fixture/blank.tif', 'title': 'Blank alternative',
                            'alternate': {'https': {'href': ''}, 'public': {'href': ' '}}},
        'notes': {'href': './notes.xml', 'roles': ['metadata'], 'title': 'Metadata sidecar'},
        'empty': {'href': ' ', 'title': 'Missing address'},
        'unsafe': {'href': 'javascript:alert(1)', 'title': '<img src=x onerror=alert(1)>'},
        'credentials': {'href': 'https://user:secret@download-fixture.test/secret.tif'},
        'invalid': None,
    }
    asset_requests = []

    def fixture(route):
        path = urlsplit(route.request.url).path
        if path in ('', '/'):
            data = {**catalog, 'links': [{'rel': 'search', 'href': host + '/search'}]}
        elif path == '/search':
            data = {'type': 'FeatureCollection', 'features': [item], 'links': []}
        else:
            asset_requests.append(route.request.url)
            # No Access-Control-Allow-Origin: navigation downloads do not need fetch CORS.
            route.fulfill(body=ATTACHMENT, content_type='application/octet-stream',
                          headers={'Content-Disposition': 'attachment; filename="population.tif"'})
            return
        route.fulfill(body=json.dumps(data), content_type='application/json',
                      headers={'Access-Control-Allow-Origin': '*'})

    page.context.route(host + '/**', fixture)
    page.locator('#preset').select_option('custom')
    page.locator('#endpoint').fill(host)
    page.locator('#connect').click()
    expect(page.locator('#search')).to_be_enabled()

    def select():
        page.locator('#search').click()
        expect(page.locator('#search')).to_be_enabled()
        page.locator('.result-card').click()
        expect(page.get_by_role('heading', name='Download dataset', exact=True)).to_be_visible()

    select()
    section = page.get_by_role('region', name='Download dataset', exact=True)
    expect(section.locator('.asset-download')).to_have_count(2)
    expect(section.locator('.asset-download').first).to_have_attribute('href', host + '/items/data.tif')
    expect(section.locator('.asset-download').nth(1)).to_have_attribute('href', host + '/second.tif')
    expect(section.get_by_role('link', name='Download Second raster (HTTPS)', exact=True)).to_be_visible()
    expect(section.get_by_role('textbox', name='Blank alternative asset address', exact=True)).to_have_value('s3://fixture/blank.tif')
    expect(section.get_by_role('link', name='Open Preview', exact=True)).to_be_visible()
    expect(section.get_by_role('link', name='Open Metadata sidecar', exact=True)).to_be_visible()
    assert page.locator('#metadata img, #metadata script, #metadata a[href^="javascript:"]').count() == 0
    assert section.locator('a[href*="user:secret"]').count() == 0
    assert not asset_requests, 'Selecting metadata must never fetch assets'
    assert page.locator('#metadata').evaluate("e => e.querySelector('section').compareDocumentPosition(e.querySelector('dl')) & Node.DOCUMENT_POSITION_FOLLOWING")
    output = Path(__file__).resolve().parents[1] / 'test-results'
    output.mkdir(exist_ok=True)
    page.screenshot(path=str(output / 'downloads-desktop.png'))
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    with page.expect_download() as result:
        section.get_by_role('link', name='Download Population raster', exact=True).click()
    assert result.value.suggested_filename == 'population.tif'
    assert Path(result.value.path()).read_bytes() == ATTACHMENT
    assert asset_requests == [host + '/items/data.tif']
    with page.expect_download() as result:
        section.get_by_role('button', name='Download item metadata (.json)', exact=True).click()
    assert json.loads(Path(result.value.path()).read_text(encoding='utf-8')) == item
    assert len(asset_requests) == 1
    # Subsequent selections must bind downloads to the current Item, including absent assets.
    restricted = {'href': host + '/restricted.tif', 'title': 'Restricted file', 'auth:refs': ['signing']}
    item['properties']['auth:schemes'] = {'signing': {'type': 'signedUrl', 'description': 'Obtain a signed URL from the provider. <script>unsafe()</script>'}}
    for assets, expected_links in [({'data': restricted}, 1), ({}, 0), ({'thumbnail': item['assets']['preview']}, 0),
                                   ({'data': item['assets']['raster']}, 1)]:
        item['id'] += '-next'
        item['assets'] = assets
        select()
        expect(section.locator('.asset-download')).to_have_count(expected_links)
        if not expected_links:
            expect(section).to_contain_text('No browser-downloadable data file is advertised')
        if assets == {'data': restricted}:
            expect(section).to_contain_text('These data links require provider authentication')
            expect(section).to_contain_text('This browser does not sign in or sign URLs')
            expect(section).to_contain_text('Obtain a signed URL from the provider.')
            assert section.locator('script').count() == 0
        expect(section).to_contain_text('metadata only')
        with page.expect_download() as result:
            section.get_by_role('button', name='Download item metadata (.json)', exact=True).click()
        assert json.loads(Path(result.value.path()).read_text(encoding='utf-8')) == item
        assert len(asset_requests) == 1

    # COG HTTPS alternatives and direct NetCDF OData URLs must use provider sign-in.
    protected_requests = []
    provider_root = 'https://browser.stac.dataspace.copernicus.eu/'
    def reject_protected(route):
        protected_requests.append(route.request.url)
        route.fulfill(status=401, body='Unauthorized')
    def provider_page(route):
        route.fulfill(content_type='text/html', body='<h1>Synthetic Copernicus sign-in page</h1>')
    page.context.route('https://download.dataspace.copernicus.eu/**', reject_protected)
    page.context.route(provider_root + '**', provider_page)
    for format in ['cog', 'nc']:
        collection = 'clms_ndvi_global_300m_10daily_v2_' + format
        product = 'c_gls_NDVI300_202512210000_GLOBE_OLCI_V2.0.1_' + format
        path = f'collections/{collection}/items/{product}'
        api_url = f'https://download.dataspace.copernicus.eu/odata/v1/Products(ccf70f3b-7b04-41f9-ade5-1443a085748e)/Nodes({product})/Nodes(file.{"tiff" if format == "cog" else "nc"})/$value'
        item.update(id=product, collection=collection, links=[{'rel': 'self', 'href': 'https://stac.dataspace.copernicus.eu/v1/' + path}])
        # Deliberately omit auth:refs for one variant: the known protected endpoint is sufficient.
        item['assets'] = {'qflag': {'href': 's3://fixture/file.tiff', 'title': 'Quality Flag on Normalized Difference Vegetation Index', 'alternate': {'https': {'href': api_url}}, 'roles': ['data']}} if format == 'cog' else {'ndvi': {'href': api_url, 'roles': ['data'], 'auth:refs': ['oidc']}}
        if format == 'cog':
            item['assets']['Product'] = {'href': api_url.split('/Nodes(')[0] + '/$value', 'title': 'Zipped product', 'roles': ['data', 'archive']}
        select()
        expect(section).to_contain_text('Copernicus downloads require sign-in')
        expect(section).to_contain_text('401 Unauthorized')
        expect(section).to_contain_text('select HTTPS if offered, then Download')
        expect(section.locator('.asset-provider')).to_have_count(2 if format == 'cog' else 1)
        expect(section.locator('.asset-provider').first).to_have_attribute('href', provider_root + path)
        assert section.locator('.asset-provider').first.get_attribute('download') is None
        expect(section.get_by_role('textbox').first).to_have_value(api_url)
        expect(section.get_by_role('textbox').first).to_have_attribute('readonly', '')
        if format == 'cog':
            expect(section).to_contain_text('find “Quality Flag on Normalized Difference Vegetation Index” (expand if needed)')
            expect(section).to_contain_text('find “Zipped product” (expand if needed)')
        assert section.locator('a[href^="https://download.dataspace.copernicus.eu"]').count() == 0
        with page.context.expect_page() as opened:
            section.locator('.asset-provider').first.click()
        popup = opened.value
        expect(popup).to_have_url(provider_root + path)
        expect(popup.locator('h1')).to_have_text('Synthetic Copernicus sign-in page')
        popup.close()
        assert not protected_requests
        with page.expect_download() as result:
            section.get_by_role('button', name='Download item metadata (.json)', exact=True).click()
        assert json.loads(Path(result.value.path()).read_text(encoding='utf-8')) == item
    item['links'] = []
    select()
    expect(section.locator('.asset-provider')).to_have_attribute('href', provider_root)
    expect(section).to_contain_text(f'search for Item “{item["id"]}”')
    item['assets'] = {'metadata': {'href': api_url, 'roles': ['metadata'], 'title': 'Product metadata'}}
    select()
    expect(section.locator('.asset-download')).to_have_count(0)
    expect(section.locator('.asset-supporting.asset-provider')).to_have_count(1)
    expect(section).to_contain_text('No browser-downloadable data file is advertised')
    expect(section).to_contain_text('Copernicus supporting files require sign-in')
    item['assets'] = {'copernicus': {'href': api_url, 'roles': ['data']}, 'public': {'href': host + '/public.tif'}, 'restricted': restricted}
    select()
    expect(section.locator('.asset-download')).to_have_count(3)
    expect(section.locator('.asset-provider')).to_have_count(1)
    expect(section).to_contain_text('Copernicus downloads require sign-in')
    expect(section).to_contain_text('This browser does not sign in or sign URLs')
    assert not protected_requests
    assert len(asset_requests) == 1
    page.context.unroute('https://download.dataspace.copernicus.eu/**', reject_protected)
    page.context.unroute(provider_root + '**', provider_page)
    page.context.unroute(host + '/**', fixture)
    print('Dataset downloads passed: attachment bytes, relative URLs, multi-file, preview, metadata-only, and selection changes', flush=True)
