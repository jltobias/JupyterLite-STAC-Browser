import assert from 'node:assert/strict';
import test from 'node:test';
import {GEOLIBRE_WEB_URL, geoLibreAssetHandoff, geoLibreBridgeURL} from '../web/geolibre-handoff.js';
import {parseGeoLibreBridgeRequest, probeGeoLibreAsset} from '../web/geolibre-bridge.js';

test('builds an exact public GeoLibre asset handoff', () => {
  const result = geoLibreAssetHandoff({href: './data.tif', base: 'https://catalog.test/items/one.json',
    type: 'image/tiff; application=geotiff; profile=cloud-optimized', roles: ['data']});
  assert.equal(result.available, true);
  assert.equal(result.source, 'https://catalog.test/items/data.tif');
  assert.equal(result.kind, 'cog');
  assert.equal(result.requiresRange, true);
  const target = new URL(result.href);
  assert.equal(target.origin + '/', GEOLIBRE_WEB_URL);
  assert.deepEqual([...target.searchParams], [['data', 'https://catalog.test/items/data.tif']]);
});

test('accepts the documented GeoLibre data formats with their Range requirements', () => {
  for (const [href, type, kind, requiresRange] of [
    ['https://data.test/extensionless', 'application/geo+json', 'geojson', false],
    ['https://data.test/extensionless', 'application/vnd.geo+json', 'geojson', false],
    ['https://data.test/features.geojson', 'application/octet-stream', 'geojson', false],
    ['https://data.test/features.json', 'application/geo+json', 'geojson', false],
    ['https://data.test/features.parquet', 'application/octet-stream', 'geoparquet', true],
    ['https://data.test/features.geoparquet', 'application/octet-stream', 'geoparquet', true],
    ['https://data.test/map.pmtiles', 'application/octet-stream', 'pmtiles', true],
    ['https://data.test/image.tiff', 'application/octet-stream', 'cog', true],
    ['https://data.test/elevation.cog', 'application/octet-stream', 'cog', true],
    ['https://data.test/tiles/ept.json', 'application/json', 'ept', false],
    ['https://data.test/cloud.copc.laz', 'application/octet-stream', 'lidar', true],
    ['https://data.test/cloud.laz', 'application/vnd.laszip+copc', 'lidar', true],
    ['https://data.test/extensionless-copc', 'application/vnd.laszip+copc', 'lidar', true],
    ['https://data.test/points.las', 'application/octet-stream', 'lidar', false],
  ]) {
    const result = geoLibreAssetHandoff({href, type, roles: ['data']});
    assert.equal(result.available, true, `${href} (${type})`);
    assert.equal(result.kind, kind);
    assert.equal(result.requiresRange, requiresRange);
  }
});

test('builds and validates a same-origin compatibility bridge URL', () => {
  const handoff = geoLibreAssetHandoff({href: 'https://data.test/image.tif', type: 'image/tiff', roles: ['data']});
  const bridge = new URL(geoLibreBridgeURL(handoff, 'https://explorer.test/app/index.html'));
  assert.equal(bridge.href.startsWith('https://explorer.test/app/geolibre-bridge.html?'), true);
  assert.deepEqual([...bridge.searchParams], [['data', 'https://data.test/image.tif'], ['kind', 'cog']]);
  const parsed = parseGeoLibreBridgeRequest(bridge.search);
  assert.equal(parsed.source, handoff.source);
  assert.equal(parsed.destination, handoff.href);
  assert.equal(parsed.requiresRange, true);
  assert.throws(() => geoLibreBridgeURL({}, 'https://explorer.test/app/'), /valid GeoLibre handoff/);
  assert.throws(() => geoLibreBridgeURL(handoff, 'file:///tmp/index.html'), /HTTP\(S\)/);
});

test('preserves extensionless LiDAR dispatch and COPC Range policy through the bridge', () => {
  for (const [type, expectedKind, requiresRange] of [
    ['application/vnd.laz', 'lidar', false],
    ['application/vnd.laszip+copc', 'copc', true],
  ]) {
    const handoff = geoLibreAssetHandoff({href: 'https://data.test/download/42', type, roles: ['data']});
    const bridge = new URL(geoLibreBridgeURL(handoff, 'https://explorer.test/app/'));
    assert.equal(bridge.searchParams.get('kind'), expectedKind);
    const parsed = parseGeoLibreBridgeRequest(bridge.search);
    assert.equal(parsed.source, 'https://data.test/download/42');
    assert.equal(parsed.kind, 'lidar');
    assert.equal(parsed.dataType, 'lidar');
    assert.equal(parsed.requiresRange, requiresRange);
    assert.deepEqual([...new URL(parsed.destination).searchParams], [
      ['data', 'https://data.test/download/42'], ['dataType', 'lidar'],
    ]);
  }
});

test('rejects malformed, protected, mismatched, and credential-bearing bridge queries', () => {
  const query = (data, kind = 'cog', extra = []) => {
    const params = new URLSearchParams([['data', data], ['kind', kind], ...extra]);
    return `?${params}`;
  };
  for (const search of [
    '',
    query('https://data.test/image.tif', 'cog', [['kind', 'cog']]),
    query('https://data.test/image.tif', 'cog', [['other', 'value']]),
    query('https://data.test/image.tif', 'geojson'),
    query('https://user:secret@data.test/image.tif'),
    query('https://data.test/image.tif?X-Amz-Signature=secret'),
    query('https://download.dataspace.copernicus.eu/odata/v1/Products(id)/$value'),
    query('http://data.test/image.tif'),
  ]) {
    assert.throws(() => parseGeoLibreBridgeRequest(search), error => {
      assert.equal(error.message, 'The GeoLibre compatibility link is invalid.');
      assert.doesNotMatch(error.message, /secret/);
      return true;
    });
  }
});

test('uses a one-byte credential-free probe and accepts a streamed 206 response', async () => {
  let call, cancelled = false;
  const request = parseGeoLibreBridgeRequest('?data=https%3A%2F%2Fdata.test%2Fimage.tif&kind=cog');
  const result = await probeGeoLibreAsset(request, {fetchImpl: async (url, options) => {
    call = {url, options};
    return {ok: true, status: 206, body: {cancel: async () => { cancelled = true; }}};
  }});
  assert.equal(result.compatible, true);
  assert.equal(call.url, request.source);
  assert.equal(call.options.method, 'GET');
  assert.deepEqual(call.options.headers, {Range: 'bytes=0-0'});
  assert.equal(call.options.credentials, 'omit');
  assert.equal(call.options.cache, 'no-store');
  assert.equal(call.options.redirect, 'follow');
  assert.equal(call.options.referrerPolicy, 'no-referrer');
  assert.equal(call.options.signal instanceof AbortSignal, true);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(cancelled, true);
});

test('falls back when a streamed asset ignores Range, while whole-file formats accept 200', async () => {
  const response = () => ({ok: true, status: 200, body: {cancel: async () => {}}});
  const worldPopLike = parseGeoLibreBridgeRequest('?data=https%3A%2F%2Fdata.test%2Fworldpop.tif&kind=cog');
  const failed = await probeGeoLibreAsset(worldPopLike, {fetchImpl: async () => response()});
  assert.equal(failed.compatible, false);
  assert.equal(failed.code, 'range');
  assert.match(failed.message, /Range/);
  const geojson = parseGeoLibreBridgeRequest('?data=https%3A%2F%2Fdata.test%2Ffeatures.geojson&kind=geojson');
  const ready = await probeGeoLibreAsset(geojson, {fetchImpl: async () => response()});
  assert.equal(ready.compatible, true);
});

test('rejects empty success statuses and exposed malformed Range metadata', async () => {
  const response = (status, headers = {}) => ({ok: status >= 200 && status < 300, status,
    headers: new Headers(headers), body: {cancel: async () => {}}});
  const cog = parseGeoLibreBridgeRequest('?data=https%3A%2F%2Fdata.test%2Fimage.tif&kind=cog');
  for (const [headers, message] of [
    [{'Content-Range': 'bytes 1-1/2', 'Content-Length': '1'}, /different bytes/],
    [{'Content-Range': 'bytes 0-0/2', 'Content-Length': '2'}, /more than/],
    [{'Content-Range': 'bytes 0-0/2', 'Content-Length': '1', 'Content-Encoding': 'gzip'}, /encoded/],
  ]) {
    const result = await probeGeoLibreAsset(cog, {fetchImpl: async () => response(206, headers)});
    assert.equal(result.compatible, false);
    assert.equal(result.code, 'range');
    assert.match(result.message, message);
  }
  const geojson = parseGeoLibreBridgeRequest('?data=https%3A%2F%2Fdata.test%2Ffeatures.geojson&kind=geojson');
  for (const candidate of [response(202), response(204), response(200, {'Content-Length': '0'})]) {
    const result = await probeGeoLibreAsset(geojson, {fetchImpl: async () => candidate});
    assert.equal(result.compatible, false);
    assert.equal(result.code, 'http');
  }
});

test('turns HTTP, network, and timeout probe failures into secret-free fallbacks', async () => {
  const request = {source: 'https://data.test/image.tif?private-value', requiresRange: true};
  const http = await probeGeoLibreAsset(request, {fetchImpl: async () =>
    ({ok: false, status: 403, body: {cancel: async () => {}}})});
  assert.deepEqual({compatible: http.compatible, code: http.code}, {compatible: false, code: 'http'});
  assert.doesNotMatch(JSON.stringify(http), /private-value/);
  const network = await probeGeoLibreAsset(request, {fetchImpl: async () => { throw new Error('private-value'); }});
  assert.equal(network.code, 'network');
  assert.doesNotMatch(JSON.stringify(network), /private-value/);
  const timeout = await probeGeoLibreAsset(request, {timeoutMs: 2, fetchImpl: async (_url, options) =>
    new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('private-value', 'AbortError'))))});
  assert.equal(timeout.code, 'timeout');
  assert.doesNotMatch(JSON.stringify(timeout), /private-value/);
});

test('requires filename dispatch for COG, GeoParquet, and PMTiles', () => {
  for (const type of [
    'application/vnd.apache.parquet', 'application/x-parquet', 'application/parquet',
    'application/vnd.pmtiles', 'image/tiff', 'image/geotiff', 'application/geotiff', 'application/x-geotiff',
  ]) {
    assert.equal(geoLibreAssetHandoff({href: 'https://data.test/extensionless', type, roles: ['data']}).available, false, type);
  }
});

test('adds the LiDAR hint only for a typed extensionless endpoint', () => {
  for (const type of ['application/vnd.las', 'application/vnd.laz', 'application/vnd.laszip', 'application/vnd.laszip+copc']) {
    const hinted = geoLibreAssetHandoff({href: 'https://data.test/download/42', type, roles: ['data']});
    assert.equal(hinted.available, true, type);
    assert.equal(hinted.dataType, 'lidar');
    assert.equal(hinted.requiresRange, type === 'application/vnd.laszip+copc');
    assert.deepEqual([...new URL(hinted.href).searchParams], [
      ['data', 'https://data.test/download/42'], ['dataType', 'lidar'],
    ]);
  }
  const named = geoLibreAssetHandoff({href: 'https://data.test/cloud.copc.laz', type: 'application/vnd.laszip+copc', roles: ['data']});
  assert.equal(named.dataType, null);
  assert.equal(new URL(named.href).searchParams.has('dataType'), false);
  assert.equal(geoLibreAssetHandoff({href: 'https://data.test/download/42', type: 'application/octet-stream'}).available, false);
  assert.equal(geoLibreAssetHandoff({href: 'https://data.test/archive.zip', type: 'application/vnd.laszip'}).available, false);
});

test('refuses supporting, authenticated, signed, protected, and unsupported inputs', () => {
  for (const role of ['thumbnail', 'overview', 'metadata', 'Thumbnail', ' metadata ']) {
    assert.match(geoLibreAssetHandoff({href: 'https://data.test/support.tif', type: 'image/tiff', roles: [role]}).reason, /preview/);
  }
  assert.match(geoLibreAssetHandoff({href: 'https://data.test/support.tif', type: 'image/tiff', roles: 'metadata'}).reason, /roles declaration/);
  assert.match(geoLibreAssetHandoff({href: 'https://data.test/data.tif', type: 'image/tiff', authRefs: ['oidc']}).reason, /authentication/);
  assert.match(geoLibreAssetHandoff({href: 'https://data.test/data.tif', type: 'image/tiff', authRefs: 'oidc'}).reason, /authentication/);
  assert.match(geoLibreAssetHandoff({href: ' ', base: 'https://data.test/item.json', type: 'image/tiff'}).reason, /public HTTP/);
  assert.match(geoLibreAssetHandoff({href: 'http://data.test/data.tif', type: 'image/tiff'}).reason, /HTTPS/);
  assert.match(geoLibreAssetHandoff({href: 'https://data.test/data.tif?X-Amz-Signature=secret', type: 'image/tiff'}).reason, /signed/);
  assert.match(geoLibreAssetHandoff({href: 'https://user:secret@data.test/data.tif', type: 'image/tiff'}).reason, /public HTTP/);
  assert.match(geoLibreAssetHandoff({href: 'https://download.dataspace.copernicus.eu/odata/v1/Products(id)/Nodes(file.tif)/%24value',
    type: 'image/tiff'}).reason, /Copernicus session token/);
  for (const key of [
    'password', 'passwd', 'authorization', 'auth', 'auth_token', 'bearer', 'bearer_token', 'credential',
    'secret', 'jwt', 'ticket', 'private_token', 'session', 'sessionid', 'session_id', 'sessionkey',
    'session_key', 'session_token', 'sid',
  ]) {
    const rejected = geoLibreAssetHandoff({href: `https://data.test/data.tif?${key}=hidden`, type: 'image/tiff'});
    assert.match(rejected.reason, /credential-bearing/, key);
    assert.equal('href' in rejected, false, key);
    assert.doesNotMatch(JSON.stringify(rejected), /hidden/, key);
  }
  for (const [href, type] of [
    ['https://data.test/data.nc', 'application/x-netcdf'],
    ['https://data.test/data.nc', 'image/tiff'],
    ['https://data.test/data.tif', 'application/x-netcdf'],
    ['https://data.test/image.jp2', 'image/jp2'],
    ['https://data.test/image.jp2', 'image/tiff'],
    ['https://data.test/data.tif', 'image/jp2'],
    ['https://data.test/archive.zip', 'image/tiff'],
    ['https://data.test/file.json', 'application/json'],
    ['https://data.test/file.fgb', 'application/geo+json'],
    ['https://data.test/readme.xml', 'application/xml'],
  ]) assert.equal(geoLibreAssetHandoff({href, type, roles: ['data']}).available, false, href);
});

test('never embeds a rejected secret in a GeoLibre destination', () => {
  for (const result of [
    geoLibreAssetHandoff({href: 'https://data.test/data.tif?sig=secret', type: 'image/tiff'}),
    geoLibreAssetHandoff({href: 'https://user:secret@data.test/data.tif', type: 'image/tiff'}),
  ]) {
    assert.equal(result.available, false);
    assert.equal('href' in result, false);
    assert.doesNotMatch(JSON.stringify(result), /secret/);
  }
});
