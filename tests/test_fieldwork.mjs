import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {
  buildFieldworkSelection, sanitizeExport, assessFieldworkRaster, buildFieldworkRasterHandoff,
  SELECTION_PROFILE, RASTER_PROFILE,
} from '../web/fieldwork-handoff.js';

const item = {
  type: 'Feature', stac_version: '1.0.0', id: 'scene-1', collection: 'demo',
  geometry: null,
  properties: {datetime: '2026-10-15T10:00:00-04:00', note: 'Bearer should-never-leak'},
  assets: {data: {href: './image.tif?token=secret&part=1', type: 'image/tiff', roles: ['data'], 'auth:refs': ['oidc'],
    alternate: {signed: {href: 'https://data.test/image.tif?X-Amz-Signature=also-secret&X-Amz-Date=20261015T000000Z&part=1'}}, secret: 'hidden'}},
  links: [{rel: 'self', href: 'https://catalog.test/items/scene-1.json?sig=item-secret'}],
};
const completedSearch = {stac_root: 'https://catalog.test/?token=root-secret', query: {bbox: [1, 2, 3, 4]},
  study_area: {shape: 'rectangle', bbox: [1, 2, 3, 4]}, retrieved_at: '2026-10-15T14:01:02Z'};

test('selection binds one owned asset, semantic roles and sanitized evidence without fetch', () => {
  let requests = 0;
  globalThis.fetch = () => { requests++; throw new Error('selection export must not fetch'); };
  const handoff = buildFieldworkSelection({item, assetKey: 'data', accessHref: item.assets.data.alternate.signed.href,
    sourceDocument: 'https://catalog.test/search?page=1', itemBase: 'https://catalog.test/items/scene-1.json',
    catalog: {url: completedSearch.stac_root}, completedSearch});
  assert.equal(handoff.profile, SELECTION_PROFILE);
  assert.deepEqual([handoff.selection.item_id, handoff.selection.asset_key], ['scene-1', 'data']);
  assert.equal(handoff.selection.original_href, './image.tif?part=1');
  assert.equal(handoff.selection.resolved_http_href, 'https://data.test/image.tif?part=1');
  assert.deepEqual(handoff.selection.source_document, {response_url: 'https://catalog.test/search?page=1',
    base_url: 'https://catalog.test/items/scene-1.json', redacted_query_parameters: []});
  assert.deepEqual(handoff.selection.declared.roles, ['data']);
  assert.deepEqual(handoff.selection.declared.auth_refs, ['oidc']);
  assert.equal(handoff.spatial.geometry_is_null, true);
  assert.equal(handoff.spatial.item_footprint, null);
  assert.deepEqual(handoff.spatial.spatial_window_readiness, {verified: false, ready: false,
    reason: 'Item geometry is null; no footprint or spatial-window readiness is inferred.'});
  assert.deepEqual(handoff.spatial.study_area_crs84.bbox, [1, 2, 3, 4]);
  assert.equal(handoff.temporal.item_datetime_utc, '2026-10-15T14:00:00.000Z');
  const serialized = JSON.stringify(handoff);
  for (const secret of ['also-secret', 'item-secret', 'root-secret', 'should-never-leak', '"hidden"']) assert(!serialized.includes(secret));
  assert.equal(requests, 0);
});

test('selection refuses absent ownership, missing relative base and unusable locations', () => {
  assert.throws(() => buildFieldworkSelection({item, assetKey: 'missing', sourceDocument: 'https://catalog.test/search'}), /owned/);
  assert.throws(() => buildFieldworkSelection({item, assetKey: 'data'}), /source-document base/);
  const broken = structuredClone(item); broken.assets.data = {href: 's3://bucket/key.tif'};
  assert.throws(() => buildFieldworkSelection({item: broken, assetKey: 'data', sourceDocument: 'https://catalog.test/search'}), /usable HTTP/);
});

test('recursive export sanitizer removes bearer values and signed query values', () => {
  const value = sanitizeExport({authorization: 'Bearer abc', nested: [
    {href: '../a.tif?api_key=nope&ok=yes'},
    {href: 'bare.tif?client_id=id&client_secret=secret&code=code&ok=yes'},
    {href: 'blob.tif?sv=v&si=i&spr=https&rscc=cache&ok=yes'},
    {href: 'https://user:password@data.test/a.tif'},
    {href: '//user:password@data.test/a.tif'},
  ]});
  assert.deepEqual(value, {authorization: '[REDACTED]', nested: [
    {href: '../a.tif?ok=yes'}, {href: 'bare.tif?ok=yes'}, {href: 'blob.tif?ok=yes'},
    {href: '[REDACTED UNSAFE URL]'}, {href: '[REDACTED UNSAFE URL]'},
  ]});
  assert.deepEqual(sanitizeExport({crs: 'EPSG:4326'}), {crs: 'EPSG:4326'});
  const clean = structuredClone(item);
  clean.assets.data = {href: './image.tif', type: 'image/tiff', roles: ['data'],
    'auth:refs': ['oauth?client_secret=auth-secret&name=provider']};
  const handoff = buildFieldworkSelection({item: clean, assetKey: 'data', sourceDocument: 'https://catalog.test/item.json',
    catalog: {url: 'https://catalog.test/?skt=azure-secret&visible=yes'}, completedSearch: null});
  assert.deepEqual(handoff.selection.declared.auth_refs, ['oauth?name=provider']);
  assert.equal(handoff.selection.access.transient_credentials_omitted, true);
  assert(!JSON.stringify(handoff).includes('auth-secret'));
  assert(!JSON.stringify(handoff).includes('azure-secret'));
  const catalogOnly = structuredClone(item);
  catalogOnly.properties = {};
  catalogOnly.assets.data = {href: './image.tif', type: 'image/tiff', roles: ['data']};
  const catalogRedaction = buildFieldworkSelection({item: catalogOnly, assetKey: 'data', sourceDocument: 'https://catalog.test/item.json',
    catalog: {title: 'landing?client_secret=catalog-only&visible=yes'}, completedSearch: null});
  assert.equal(catalogRedaction.discovery.catalog.title, 'landing?visible=yes');
  assert.equal(catalogRedaction.selection.access.transient_credentials_omitted, true);
});

test('compatibility names every FieldWork raster mismatch', () => {
  const result = assessFieldworkRaster({width: 600, height: 500, bands: 3, epsg: 3857, pixelIsArea: false, northUp: false,
    byteCount: 5000001, geoKeys: {}, modelTransformation: true, origin: [NaN, 90], resolution: [-1, 1], bounds: [-181, -91, 181, 91]});
  assert.equal(result.compatible, false);
  for (const phrase of ['one band', 'EPSG:4326', 'PixelIsArea raster', 'north-up', 'geographic WGS84', 'explicit PixelIsArea',
    'no ModelTransformation', 'positive-X/negative-Y', 'CRS84', '262,144', '5,000,000']) assert(result.reasons.some(reason => reason.includes(phrase)));
});

test('compatibility rejects invalid sizes, byte limits and inconsistent grids', () => {
  const valid = {width: 8, height: 4, bands: 1, epsg: 4326, pixelIsArea: true, northUp: true, byteCount: 5000000,
    geoKeys: {model_type: 2, raster_type: 1, geographic_type: 4326, angular_units: 9102}, modelTransformation: false,
    bounds: [10, 20, 18, 24], origin: [10, 24], resolution: [1, -1]};
  assert.equal(assessFieldworkRaster(valid).compatible, true);
  for (const changed of [
    {width: 0}, {height: -1}, {byteCount: 0}, {byteCount: 5000001},
    {geoKeys: {...valid.geoKeys, geographic_type: 4269}}, {modelTransformation: true},
    {resolution: [0, -1]}, {bounds: [10, 20, 17, 24]}, {bounds: [-181, 20, -173, 24]},
  ]) assert.equal(assessFieldworkRaster({...valid, ...changed}).compatible, false, JSON.stringify(changed));
});

test('compatible raster sidecar hashes the exact saved bytes and keeps boundaries distinct', async () => {
  const buffer = new TextEncoder().encode('synthetic geotiff bytes').buffer;
  const raster = {width: 8, height: 4, bands: 1, epsg: 4326, pixelIsArea: true, northUp: true,
    geoKeys: {model_type: 2, raster_type: 1, geographic_type: 4326, angular_units: 9102}, modelTransformation: false,
    bounds: [10, 20, 18, 24], origin: [10, 24], resolution: [1, -1]};
  const handoff = await buildFieldworkRasterHandoff({buffer, raster,
    sourceLineage: {source_url: 'https://data.test/a.tif?token=gone', asset_key: 'data'},
    clippingBoundary: {crs: 'CRS84', bbox: [11, 21, 17, 23]}, acquisitionBoundary: {crs: 'EPSG:4326', bounds: raster.bounds}});
  assert.equal(handoff.profile, RASTER_PROFILE);
  assert.equal(handoff.raster.byte_count, buffer.byteLength);
  assert.equal(handoff.raster.sha256, createHash('sha256').update(new Uint8Array(buffer)).digest('hex'));
  assert.notDeepEqual(handoff.raster.bounds.clipping_boundary, handoff.raster.bounds.acquisition_boundary);
  assert(!JSON.stringify(handoff).includes('gone'));
  assert.deepEqual(handoff.fieldwork.satisfied_constraints, {crs: 'EPSG:4326', bands: 1, pixel_is_area: true, north_up: true,
    geo_keys: {model_type: 2, raster_type: 1, geographic_type: 4326, angular_units: 9102}, model_transformation: false,
    grid_rule: 'finite positive-X/negative-Y grid with consistent ordered CRS84 bounds', max_cells: 262144, max_bytes: 5000000});
});
