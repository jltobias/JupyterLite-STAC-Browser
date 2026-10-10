import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {deflateSync} from 'node:zlib';
import {RangeSource, cropWindow, clipRaster, CLIP_LIMITS, writeGeoTIFF} from '../web/raster-clip.js';
import {copernicusSubset} from '../web/copernicus-subset.js';
const require = createRequire(import.meta.url);
const GeoTIFF = require('../web/vendor/geotiff-3.0.5.js');
const proj4 = require('../web/vendor/proj4-2.19.10.js');
const folder = process.env.RASTER_FIXTURES || new URL('../test-results/raster-fixtures/', import.meta.url).pathname.replace(/^\/(?=[A-Z]:)/, '');
const manifests = JSON.parse(readFileSync(`${folder}/manifest.json`));
function server(bytes, requests = []) {
  return async (url, options) => {
    assert.equal(options.credentials, 'omit');
    const [, a, b] = /^bytes=(\d+)-(\d+)$/.exec(options.headers.Range);
    const start = Number(a), end = Math.min(Number(b), bytes.length - 1);
    assert(start >= 0 && end >= start); requests.push([start, end]);
    return new Response(bytes.subarray(start, end + 1), {status: 206, headers: {'Content-Range': `bytes ${start}-${end}/${bytes.length}`, ETag: 'fixture'}});
  };
}
for (const {name, bbox} of manifests) test(`source pixels: ${name}`, async () => {
  const bytes = readFileSync(`${folder}/${name}.tif`), ranges = [];
  const result = await clipRaster({url: 'https://raster.test/source.tif', bbox, provenance: {asset_key: 'data'}}, {GeoTIFF, proj4, fetcher: server(bytes, ranges)});
  assert.equal(result.epsg > 0, true);
  assert(result.provenance.transferred_bytes < bytes.length, 'small crop must not transfer the full source');
  assert(ranges.length > 1 && ranges.every(([a, b]) => b - a + 1 < bytes.length));
  const output = await (await GeoTIFF.fromArrayBuffer(result.buffer)).getImage();
  const embedded = JSON.parse((await output.getGDALMetadata()).STAC_BROWSER_PROVENANCE);
  assert.deepEqual(embedded, result.provenance);
  assert.equal(embedded.range_requests, ranges.length);
  assert.equal(embedded.transferred_bytes, ranges.reduce((sum, [start, end]) => sum + end - start + 1, 0));
  writeFileSync(`${folder}/${name}-crop.tif`, new Uint8Array(result.buffer));
});
test('reject ignored Range without consuming its body', async () => {
  let canceled = false, reads = 0;
  const source = new RangeSource('https://raster.test/data', {fetcher: async () => ({status: 200, body: {cancel: async () => { canceled = true; }, getReader: () => { reads++; }}})});
  await assert.rejects(source.fetch([{offset: 0, length: 16}]), /ignored HTTP Range/);
  assert(canceled); assert.equal(reads, 0);
});
test('accept hidden range headers but reject invalid exposed ranges, auth, excessive bodies and slow/canceled requests', async () => {
  const hidden = new RangeSource('https://raster.test/data', {fetcher: async () => new Response('ab', {status: 206})});
  assert.equal(new TextDecoder().decode((await hidden.fetch([{offset: 0, length: 2}]))[0]), 'ab');
  for (const response of [new Response('a', {status: 206, headers: {'Content-Range': 'bytes 10-11/100'}}), new Response('', {status: 401}), new Response('too long', {status: 206, headers: {'Content-Range': 'bytes 0-1/100'}})]) {
    const source = new RangeSource('https://raster.test/data', {fetcher: async () => response});
    await assert.rejects(source.fetch([{offset: 0, length: 2}]), /Content-Range|401|exceeded/);
  }
  const controller = new AbortController(); controller.abort(); let calls = 0;
  await assert.rejects(new RangeSource('https://raster.test/data', {signal: controller.signal, fetcher: async () => { calls++; }}).fetch([{offset: 0, length: 2}]), /abort/i);
  assert.equal(calls, 0);
  const source = new RangeSource('https://raster.test/data', {limits: {...CLIP_LIMITS, requestMs: 5}, fetcher: (url, {signal}) => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Timeout', 'AbortError'))))});
  await assert.rejects(source.fetch([{offset: 0, length: 2}]), /timed out/);
});
test('bounds, partial intersection, grid alignment, dateline and unsupported CRS', () => {
  const grid = {epsg: 4326, x: 10, y: 20, dx: .01, dy: -.01, width: 128, height: 128};
  assert.deepEqual(cropWindow([10.175, 19.385, 10.455, 19.785], grid, p => p).window, [17, 21, 46, 62]);
  assert.deepEqual(cropWindow([9, 19, 10.1, 21], grid, p => p).window, [0, 0, 10, 100]);
  assert.throws(() => cropWindow([0, 0, 1, 1], grid, p => p), /does not overlap/);
  assert.throws(() => cropWindow([179, -1, -179, 1], grid, p => p), /antimeridian/);
  assert.throws(() => cropWindow([10, 19, 11, 20], {...grid, epsg: 3035}, p => p), /Unsupported CRS/);
  assert.throws(() => cropWindow([10, 19, 11, 20], {...grid, dy: 1}, p => p), /north-up/);
});
test('resource limits apply before reading raster blocks', async () => {
  const bytes = readFileSync(`${folder}/integer.tif`);
  for (const limits of [{output: 100}, {block: 1000}, {decoded: 100}, {metadata: 50}, {transfer: 32}, {requests: 1}]) {
    await assert.rejects(clipRaster({url: 'https://raster.test/data', bbox: manifests[0].bbox}, {GeoTIFF, proj4, fetcher: server(bytes), limits: {...CLIP_LIMITS, ...limits}}), /resource limits/);
  }
});
test('heterogeneous sample types and rotated affine grids fail explicitly', async () => {
  const source = readFileSync(`${folder}/integer.tif`);
  const bytes = new Uint8Array(source), view = new DataView(bytes.buffer), ifd = view.getUint32(4, true), count = view.getUint16(ifd, true);
  for (let i = 0; i < count; i++) {
    const at = ifd + 2 + i * 12;
    if (view.getUint16(at, true) === 339) view.setUint16(view.getUint32(at + 8, true) + 2, 3, true);
  }
  await assert.rejects(clipRaster({url: 'https://raster.test/data', bbox: manifests[0].bbox}, {GeoTIFF, proj4, fetcher: server(bytes)}), /heterogeneous/);
  const rotated = writeGeoTIFF(new Uint8Array(100), {width: 10, height: 10, samples: 1, bits: 8, format: 1,
    tags: [[262, 3, [1]], [34264, 12, [1, .1, 0, 10, .1, -1, 0, 20, 0, 0, 1, 0, 0, 0, 0, 1]], [34735, 3, [1, 1, 0, 2, 1024, 0, 1, 2, 2048, 0, 1, 4326]]]});
  await assert.rejects(clipRaster({url: 'https://raster.test/data', bbox: manifests[0].bbox}, {GeoTIFF, proj4, fetcher: server(new Uint8Array(rotated))}), /Rotated/);
});
test('reject genuine FillOrder=2 and internal mask TIFFs, including masks after the base IFD', async () => {
  for (const [name, message] of [['fill_order_2', /FillOrder/], ['internal_mask', /validity masks/]]) {
    const bytes = readFileSync(`${folder}/${name}.tif`);
    await assert.rejects(clipRaster({url: 'https://raster.test/data', bbox: manifests[0].bbox}, {GeoTIFF, proj4, fetcher: server(bytes)}), message);
  }
});
test('SubIFDs are rejected conservatively and cyclic/larger IFD chains remain bounded', async () => {
  const base = writeGeoTIFF(new Uint8Array(100), {width: 10, height: 10, samples: 1, bits: 8, format: 1,
    tags: [[262, 3, [1]], [330, 4, [42]]]});
  await assert.rejects(clipRaster({url: 'https://raster.test/data', bbox: manifests[0].bbox}, {GeoTIFF, proj4, fetcher: server(new Uint8Array(base))}), /SubIFDs/);
  const cyclic = new Uint8Array(readFileSync(`${folder}/integer.tif`)), view = new DataView(cyclic.buffer), ifd = view.getUint32(4, true);
  view.setUint32(ifd + 2 + view.getUint16(ifd, true) * 12, ifd, true);
  await assert.rejects(clipRaster({url: 'https://raster.test/data', bbox: manifests[0].bbox}, {GeoTIFF, proj4, fetcher: server(cyclic)}), /cyclic/);
  const source = readFileSync(`${folder}/integer.tif`), chain = new Uint8Array(source.length + 65 * 6), chainView = new DataView(chain.buffer);
  chain.set(source);
  chainView.setUint32(ifd + 2 + chainView.getUint16(ifd, true) * 12, source.length, true);
  for (let i = 0; i < 64; i++) chainView.setUint32(source.length + i * 6 + 2, source.length + (i + 1) * 6, true);
  await assert.rejects(clipRaster({url: 'https://raster.test/data', bbox: manifests[0].bbox}, {GeoTIFF, proj4, fetcher: server(chain)}), /resource limits/);
});
test('Deflate expansion exceeding declared block dimensions is rejected under normal limits', async () => {
  const base = writeGeoTIFF(new Uint8Array(256), {width: 16, height: 16, samples: 1, bits: 8, format: 1,
    tags: [[262, 3, [1]], [33550, 12, [.01, .01, 0]], [33922, 12, [0, 0, 0, 10, 20, 0]],
      [34735, 3, [1, 1, 0, 2, 1024, 0, 1, 2, 2048, 0, 1, 4326]]]});
  const payload = deflateSync(new Uint8Array(257)), malformed = new Uint8Array(base.byteLength + payload.length);
  malformed.set(new Uint8Array(base)); malformed.set(payload, base.byteLength);
  const view = new DataView(malformed.buffer), ifd = view.getUint32(4, true);
  for (let i = 0; i < view.getUint16(ifd, true); i++) {
    const at = ifd + 2 + i * 12, tag = view.getUint16(at, true);
    if (tag === 259) view.setUint16(at + 8, 8, true);
    if (tag === 273) view.setUint32(at + 8, base.byteLength, true);
    if (tag === 279) view.setUint32(at + 8, payload.length, true);
  }
  await assert.rejects(clipRaster({url: 'https://raster.test/data', bbox: [10.02, 19.9, 10.1, 19.98]}, {GeoTIFF, proj4, fetcher: server(malformed)}), /resource limits/);
});
test('writer handles metadata far beyond a fixed TIFF header', async () => {
  const description = 'long metadata '.repeat(3000);
  const buffer = writeGeoTIFF(new Int16Array([-9999, 3, 6, 9]), {width: 2, height: 2, samples: 1, bits: 16, format: 2, tags: [[270, 2, description], [262, 3, [1]]]});
  const image = await (await GeoTIFF.fromArrayBuffer(buffer)).getImage();
  assert.equal((await image.getFileDirectory().loadValue('ImageDescription')).replace(/\0$/, ''), description);
  assert.deepEqual(Array.from(await image.readRasters({interleave: true})), [-9999, 3, 6, 9]);
});
test('verified provider mappings, exact AOI and NetCDF limitation', () => {
  const item = {id: 'exact', collection: 'clms_ndvi_global_300m_10daily_v2_cog', properties: {datetime: '2025-12-21T00:00:00Z'}};
  for (const key of ['ndvi', 'nobs', 'qflag', 'unc']) {
    const mapped = copernicusSubset(item, key, {href: 'file.tif'}), plan = mapped.create([30, -1, 31, 1]), url = new URL(plan.url);
    assert.equal(url.searchParams.get('datasetId'), 'COPERNICUS_CLMS_NDVI_300M_10DAILY_V2');
    assert.equal(url.searchParams.get('clmsSelectedPath'), 'Vegetation Indices');
    assert.equal(url.searchParams.get('toTime'), '2025-12-21T23:59:59.999Z');
    const script = atob(url.searchParams.get('evalscript'));
    assert(script.includes(key.toUpperCase())); assert(script.includes(key === 'unc' ? 'INT16' : 'UINT8')); assert(script.includes('units: "DN"'));
    assert.deepEqual(plan.aoi.features[0].geometry.coordinates[0], [[30, -1], [31, -1], [31, 1], [30, 1], [30, -1]]);
  }
  for (const key of ['unknown', 'constructor', 'toString', '__proto__']) assert.equal(copernicusSubset(item, key, {}), null);
  assert.equal(copernicusSubset({...item, collection: item.collection.replace('v2', 'v3')}, 'ndvi', {}), null);
  assert.match(copernicusSubset({...item, collection: item.collection.replace('_cog', '_nc')}, 'ndvi', {}).unavailable, /NetCDF clipping unavailable/);
});
