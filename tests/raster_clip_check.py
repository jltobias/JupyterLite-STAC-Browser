"""Generate real TIFF fixtures with GDAL/rasterio, run JS crops, independently verify them."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parents[1]
BBOX = [10.175, 19.385, 10.455, 19.785]


def raster_bytes(dtype='int16', count=3, crs='EPSG:4326', compression='deflate', transform=None, long_metadata=True, point=False, sparse_nan=False,
                 height=128, tiled=True, predictor=None, color=None, mask=False, overviews=False, **extra):
    transform = transform or from_origin(10, 20, .01, .01)
    values = np.arange(count * height * 128).reshape(count, height, 128) % 1000
    values = (values / 8 - 40 if dtype.startswith('float') else values).astype(dtype)
    nodata = 255 if dtype == 'uint8' else -9999 if dtype.startswith(('int', 'float')) else 65535
    if sparse_nan:
        nodata = float('nan')
        values[:, 16:32, 16:32] = nodata
        extra['sparse_ok'] = True
    values[:, 24, 20] = nodata
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), MemoryFile() as memory:
        with memory.open(driver='GTiff', width=128, height=height, count=count, dtype=dtype, crs=crs,
                         transform=transform, nodata=nodata, tiled=tiled, blockxsize=16 if tiled else 128, blockysize=16,
                         compress=compression, predictor=predictor or (3 if dtype.startswith('float') and compression == 'deflate' else 1), **extra) as dataset:
            dataset.write(values)
            dataset.descriptions = tuple(f'Source band {i}' for i in range(count))
            dataset.scales = tuple(.01 * (i + 1) for i in range(count))
            dataset.offsets = tuple(-10.0 * i for i in range(count))
            for i in range(count):
                dataset.update_tags(i + 1, unit='source units', description='keep band metadata',
                                    STATISTICS_MINIMUM='-9999', STATISTICS_MAXIMUM='999', STATISTICS_MEAN='123',
                                    STATISTICS_HISTOBINVALUES='1|2|3', HISTOGRAM_MIN='-9999', HISTOGRAM_MAX='999')
            dataset.update_tags(source='Synthetic independent GDAL fixture', large_metadata='m' * (9000 if long_metadata else 10),
                                STATISTICS_VALID_PERCENT='99', HISTOGRAM='whole-source histogram')
            if point:
                dataset.update_tags(AREA_OR_POINT='Point')
            if color == 'rgb':
                dataset.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
            elif color == 'alpha':
                dataset.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
            elif color == 'palette':
                dataset.write_colormap(1, {i: (i, 255 - i, i // 2, 255) for i in range(256)})
            if mask:
                validity = np.full((height, 128), 255, dtype='uint8')
                validity[22:26, 19:23] = 0
                dataset.write_mask(validity)
            if overviews:
                dataset.build_overviews([2, 4], Resampling.nearest)
        return memory.read()


def fill_order_fixture():
    """Encode genuine FillOrder=2 bytes, then check them using libtiff/GDAL."""
    original = raster_bytes(dtype='uint8', count=1, compression='none')
    data = bytearray(original)
    ifd = struct.unpack_from('<I', data, 4)[0]
    count = struct.unpack_from('<H', data, ifd)[0]
    entries = [bytes(data[ifd + 2 + i * 12:ifd + 14 + i * 12]) for i in range(count)]
    tags = {struct.unpack_from('<H', entry)[0]: entry for entry in entries}
    def longs(tag):
        _, field_type, length, offset = struct.unpack('<HHII', tags[tag])
        format = 'H' if field_type == 3 else 'I'
        if length * struct.calcsize(format) <= 4:
            return struct.unpack_from('<' + format * length, tags[tag], 8)
        return struct.unpack_from('<' + format * length, data, offset)
    reverse_bits = bytes(int(f'{i:08b}'[::-1], 2) for i in range(256))
    for offset, size in zip(longs(324), longs(325)):
        data[offset:offset + size] = data[offset:offset + size].translate(reverse_bits)
    # PlanarConfiguration=1 is the default; use that directory slot for FillOrder.
    del tags[284]
    tags[266] = struct.pack('<HHII', 266, 3, 1, 2)
    for i, tag in enumerate(sorted(tags)):
        data[ifd + 2 + i * 12:ifd + 14 + i * 12] = tags[tag]
    with MemoryFile(original) as before, MemoryFile(bytes(data)) as after:
        with before.open() as expected, after.open() as actual:
            np.testing.assert_array_equal(actual.read(), expected.read())
    return bytes(data)


ATTACHMENT = raster_bytes()


def fulfill_raster(route, requests=None):
    """A real tiled attachment for navigation, or an exact single-range response."""
    header = route.request.headers.get('range')
    if requests is not None:
        requests.append(header)
    if header:
        start, end = (int(value) for value in header.removeprefix('bytes=').split('-'))
        end = min(end, len(ATTACHMENT) - 1)
        route.fulfill(status=206, body=ATTACHMENT[start:end + 1], content_type='image/tiff',
                      headers={'Content-Range': f'bytes {start}-{end}/{len(ATTACHMENT)}',
                               'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'Content-Range'})
    else:
        route.fulfill(body=ATTACHMENT, content_type='application/octet-stream',
                      headers={'Content-Disposition': 'attachment; filename="population.tif"'})


def check_crop_downloads(page, catalog, original):
    import copy
    from playwright.sync_api import expect
    host = 'https://raster-fixture.test'
    item = copy.deepcopy(original)
    item.update(id='real-raster', collection='fixture', links=[{'rel': 'self', 'href': host + '/item.json'}])
    item['assets'] = {'data': {'href': './source.tif', 'type': 'image/tiff', 'roles': ['data']}}
    requests, pending, static_pending, downloads, searches = [], [], [], [], []
    mode = ['range']
    def route_fixture(route):
        if route.request.url.endswith('/source.tif'):
            if mode[0] == 'pending':
                pending.append(route)
            elif mode[0] == 'ignored':
                requests.append(route.request.headers.get('range'))
                route.fulfill(status=200, body=ATTACHMENT, content_type='image/tiff', headers={'Access-Control-Allow-Origin': '*'})
            else:
                fulfill_raster(route, requests)
            return
        if '/search' in route.request.url:
            searches.append(route.request.url)
            data = {'type': 'FeatureCollection', 'features': [item], 'links': [{'rel': 'next', 'href': host + '/page2'}]}
        elif route.request.url.endswith('/page2'):
            updated = copy.deepcopy(item)
            updated['properties']['title'] = 'Refreshed raster metadata'
            data = {'type': 'FeatureCollection', 'features': [updated], 'links': []}
        elif route.request.url.endswith('/slow-item.json'):
            static_pending.append(route)
            return
        else:
            data = {**catalog, 'links': [{'rel': 'search', 'href': host + '/search'},
                                       {'rel': 'item', 'href': host + '/slow-item.json', 'title': 'Delayed static Item'}]}
        route.fulfill(body=json.dumps(data), content_type='application/json', headers={'Access-Control-Allow-Origin': '*'})
    page.context.route(host + '/**', route_fixture)
    def record_download(download):
        downloads.append(download)
    page.on('download', record_download)
    page.locator('#preset').select_option('custom')
    page.locator('#endpoint').fill(host)
    page.locator('#connect').click()
    expect(page.locator('#search')).to_be_enabled()
    page.locator('#spatial-mode').select_option('none')
    page.locator('#search').click()
    page.locator('.result-card').click()
    page.locator('#bbox').fill(','.join(map(str, BBOX)))
    page.locator('#bbox').press('Tab')
    expect(page.locator('.crop-bounds')).to_contain_text('Used in every search mode')
    assert not requests
    with page.expect_download() as downloaded:
        page.locator('.asset-clip').click()
    verify_crop(ATTACHMENT, Path(downloaded.value.path()).read_bytes())
    expect(page.locator('.crop-status')).to_contain_text('Saved 29 × 41 pixels in EPSG:4326')
    assert len(searches) == 1 and all(requests)
    assert sum(int(r.split('-')[1]) - int(r.split('=')[1].split('-')[0]) + 1 for r in requests) < len(ATTACHMENT)
    with page.expect_download() as provenance:
        page.get_by_role('button', name='Download crop provenance (.json)').click()
    assert json.loads(Path(provenance.value.path()).read_text())['requested_bbox'] == BBOX
    # An invalid bbox is rejected even when search uses no spatial filter.
    count = len(requests)
    page.locator('#bbox').fill('invalid')
    page.locator('.asset-clip').click()
    expect(page.locator('.crop-status')).to_contain_text('Bbox must be')
    assert len(requests) == count
    page.locator('#bbox').fill(','.join(map(str, BBOX)))
    page.locator('#bbox').press('Tab')
    mode[0] = 'ignored'
    page.locator('.asset-clip').click()
    expect(page.locator('.crop-status')).to_contain_text('Provider ignored HTTP Range')
    assert len(downloads) == 2
    # Hold a real worker request; Cancel, bbox editing and Item selection must
    # terminate it without a stale attachment. The map remains interactive.
    for action in ['cancel', 'bbox', 'item', 'draw', 'pagination', 'static']:
        mode[0] = 'pending'
        with page.expect_event('worker') as started:
            page.locator('.asset-clip').click()
        worker = started.value
        expect(page.locator('.crop-cancel')).to_be_visible()
        page.wait_for_timeout(150)
        page.locator('.leaflet-control-zoom-in').click()
        # Prove the app terminated the actual worker before the test cleans up
        # network routes. A removed worker.terminate() must fail this assertion.
        with worker.expect_event('close', timeout=5000):
            if action == 'cancel':
                page.locator('.crop-cancel').click()
            elif action == 'bbox':
                page.locator('#bbox').fill('10.18,19.39,10.45,19.78')
                page.locator('#bbox').press('Tab')
            elif action == 'draw':
                page.locator('#draw-area').click()
            elif action == 'static':
                page.get_by_role('button', name='item · Delayed static Item', exact=True).click()
            elif action == 'pagination':
                page.locator('#more').click()
            else:
                page.locator('.result-card').click()
        if action == 'draw':
            page.locator('#cancel-draw').click()
        if action == 'pagination':
            expect(page.locator('#metadata h3').first).to_have_text('Refreshed raster metadata')
            expect(page.locator('.result-card.selected')).to_contain_text('Refreshed raster metadata')
        if action == 'static':
            # Keep the new Item unresolved while proving the old crop is gone.
            page.wait_for_timeout(100)
            assert static_pending and len(downloads) == 2
            expect(page.locator('.crop-status')).to_contain_text('canceled')
            static_pending.pop().fulfill(body=json.dumps(item), content_type='application/json', headers={'Access-Control-Allow-Origin': '*'})
            expect(page.locator('#search')).to_be_enabled()
        expect(page.locator('.asset-clip')).to_be_enabled()
        while pending:
            try:
                pending.pop().abort()
            except Exception:
                pass  # Worker termination may have already closed the route.
        page.wait_for_timeout(100)
        assert len(downloads) == 2
    # Polygon envelopes and drawing validation are independent of search mode.
    mode[0] = 'range'
    page.locator('#bbox').fill(','.join(map(str, BBOX)))
    page.locator('#bbox').press('Tab')
    page.locator('#polygon-area').click()
    expect(page.locator('.crop-bounds')).to_contain_text('polygon envelope')
    with page.expect_download() as polygon_download:
        page.locator('.asset-clip').click()
    verify_crop(ATTACHMENT, Path(polygon_download.value.path()).read_bytes())
    page.locator('#draw-area').click()
    page.locator('.asset-clip').click()
    expect(page.locator('.crop-status')).to_contain_text('Finish or cancel drawing')
    page.locator('#cancel-draw').click()
    assert len(searches) == 1
    for preview in ['overview', 'thumbnail']:
        item['assets']['data']['roles'] = ['data', preview]
        page.locator('#search').click()
        expect(page.locator('#search')).to_be_enabled()
        page.locator('.result-card').click()
        expect(page.locator('.asset-clip, .provider-subset')).to_have_count(0)
        expect(page.locator('.clip-unavailable')).to_contain_text('not source raster data')
        expect(page.locator('.asset-download')).to_have_count(1)
    page.context.unroute(host + '/**', route_fixture)
    page.remove_listener('download', record_download)
    print('Raster UI passed: independent pixel verification, ranges, no-filter/polygon bbox, ignored Range, Cancel and stale selection.', flush=True)


def verify_crop(source, output, bbox=BBOX):
    with MemoryFile(source) as source_memory, MemoryFile(output) as output_memory:
        with source_memory.open() as src, output_memory.open() as dst:
            bounds = transform_bounds('EPSG:4326', src.crs, *bbox, densify_pts=256)
            raw = rasterio.windows.from_bounds(*bounds, transform=src.transform)
            snap = lambda v: round(v) if abs(v - round(v)) < 1e-7 else v
            left, top = max(0, math.floor(snap(raw.col_off))), max(0, math.floor(snap(raw.row_off)))
            right = min(src.width, math.ceil(snap(raw.col_off + raw.width)))
            bottom = min(src.height, math.ceil(snap(raw.row_off + raw.height)))
            window = Window(left, top, right - left, bottom - top)
            assert (dst.width, dst.height, dst.count) == (window.width, window.height, src.count)
            np.testing.assert_array_equal(dst.read(), src.read(window=window))
            assert dst.crs == src.crs
            assert dst.transform.almost_equals(src.window_transform(window), precision=1e-8)
            assert dst.nodata == src.nodata or (math.isnan(dst.nodata) and math.isnan(src.nodata))
            assert dst.dtypes == src.dtypes
            assert dst.colorinterp == src.colorinterp
            if ColorInterp.palette in src.colorinterp:
                assert dst.colormap(1) == src.colormap(1)
            assert dst.descriptions == src.descriptions
            assert dst.scales == src.scales and dst.offsets == src.offsets
            for band in range(1, src.count + 1):
                assert dst.tags(band) == {key: value for key, value in src.tags(band).items()
                                          if not key.startswith(('STATISTICS_', 'HISTOGRAM'))}
            for key, value in src.tags().items():
                if key.startswith(('STATISTICS_', 'HISTOGRAM')):
                    assert key not in dst.tags()
                else:
                    assert dst.tags()[key] == value
            provenance = json.loads(dst.tags()['STAC_BROWSER_PROVENANCE'])
            assert provenance['requested_bbox'] == bbox
            assert provenance['pixel_window'] == [left, top, right, bottom]
            assert provenance['reader'] == 'GeoTIFF.js 3.0.5'
            assert provenance['transferred_bytes'] > 0 and provenance['range_requests'] > 0


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    fixtures = []
    cases = [('integer', {}), ('uint8', dict(dtype='uint8', count=1, compression='none')),
             ('uint32', dict(dtype='uint32', count=2)), ('int32', dict(dtype='int32', count=2)),
             ('float', dict(dtype='float32')), ('float64', dict(dtype='float64', count=1)),
             ('lzw', dict(compression='lzw')), ('point', dict(point=True)),
             ('planar', dict(interleave='band')), ('bigtiff', dict(BIGTIFF='YES')),
             ('sparse_nan', dict(dtype='float32', sparse_nan=True)),
             ('strips', dict(tiled=False)), ('partial_strip', dict(tiled=False, height=70)),
             ('horizontal_predictor', dict(predictor=2)),
             ('rgb', dict(dtype='uint8', color='rgb', photometric='RGB')),
             ('palette', dict(dtype='uint8', count=1, color='palette')),
             ('alpha', dict(dtype='uint8', count=4, color='alpha', photometric='RGB')),
             ('overviews', dict(overviews=True)),
             ('mercator', dict(crs='EPSG:3857', transform=from_origin(1000000, 2000000, 30, 30))),
             ('utm', dict(crs='EPSG:32632', transform=from_origin(500000, 1000000, 10, 10))),
             ('utm_south', dict(crs='EPSG:32736', transform=from_origin(500000, 8000000, 10, 10)))]
    for name, options in cases:
        data = raster_bytes(**options)
        (directory / f'{name}.tif').write_bytes(data)
        bbox = BBOX
        if name == 'partial_strip':
            bbox = [10.175, 19.30, 10.455, 19.355]
        if 'crs' in options:
            transform = options['transform']
            corners = (transform * (17.5, 61.5)) + (transform * (45.5, 21.5))
            bbox = list(transform_bounds(options['crs'], 'EPSG:4326', *corners, densify_pts=256))
        fixtures.append({'name': name, 'bbox': bbox})
    (directory / 'fill_order_2.tif').write_bytes(fill_order_fixture())
    masked = raster_bytes(mask=True, overviews=True)
    with MemoryFile(masked) as memory:
        with memory.open() as dataset:
            assert dataset.dataset_mask()[24, 20] == 0
            assert dataset.dataset_mask()[23, 22] == 0  # Valid stored data excluded by internal mask.
            assert dataset.overviews(1) == [2, 4]
    (directory / 'internal_mask.tif').write_bytes(masked)
    (directory / 'manifest.json').write_text(json.dumps(fixtures), encoding='utf-8')
    return fixtures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate-only', action='store_true')
    args = parser.parse_args()
    directory = ROOT / 'test-results/raster-fixtures'
    fixtures = generate(directory)
    if args.generate_only:
        return
    local_node = ROOT / '.tools/node-v22.17.0-win-x64/node.exe'
    node = str(local_node) if local_node.exists() else shutil.which('node')
    subprocess.run([node, '--test', 'tests/test_raster_clip.mjs'], cwd=ROOT, check=True,
                   env={**os.environ, 'RASTER_FIXTURES': str(directory)})
    for fixture in fixtures:
        verify_crop((directory / f'{fixture["name"]}.tif').read_bytes(),
                    (directory / f'{fixture["name"]}-crop.tif').read_bytes(), fixture['bbox'])
    print(f'Independent rasterio verification passed: {len(fixtures)} crops, pixels, CRS, transform, NoData and band metadata.', flush=True)


if __name__ == '__main__':
    main()
