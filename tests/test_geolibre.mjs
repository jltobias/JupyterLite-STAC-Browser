import assert from 'node:assert/strict';
import test from 'node:test';
import {GEOLIBRE_WEB_URL, geoLibreAssetHandoff} from '../web/geolibre-handoff.js';

test('builds an exact public GeoLibre asset handoff', () => {
  const result = geoLibreAssetHandoff({href: './data.tif', base: 'https://catalog.test/items/one.json',
    type: 'image/tiff; application=geotiff; profile=cloud-optimized', roles: ['data']});
  assert.equal(result.available, true);
  assert.equal(result.source, 'https://catalog.test/items/data.tif');
  assert.equal(result.kind, 'cog');
  const target = new URL(result.href);
  assert.equal(target.origin + '/', GEOLIBRE_WEB_URL);
  assert.deepEqual([...target.searchParams], [['data', 'https://catalog.test/items/data.tif']]);
});

test('accepts the documented GeoLibre data formats', () => {
  for (const [href, type, kind] of [
    ['https://data.test/extensionless', 'application/geo+json', 'geojson'],
    ['https://data.test/extensionless', 'application/vnd.geo+json', 'geojson'],
    ['https://data.test/features.geojson', 'application/octet-stream', 'geojson'],
    ['https://data.test/features.json', 'application/geo+json', 'geojson'],
    ['https://data.test/features.parquet', 'application/octet-stream', 'geoparquet'],
    ['https://data.test/features.geoparquet', 'application/octet-stream', 'geoparquet'],
    ['https://data.test/map.pmtiles', 'application/octet-stream', 'pmtiles'],
    ['https://data.test/image.tiff', 'application/octet-stream', 'cog'],
    ['https://data.test/elevation.cog', 'application/octet-stream', 'cog'],
    ['https://data.test/tiles/ept.json', 'application/json', 'ept'],
    ['https://data.test/cloud.copc.laz', 'application/octet-stream', 'lidar'],
    ['https://data.test/points.las', 'application/octet-stream', 'lidar'],
  ]) {
    const result = geoLibreAssetHandoff({href, type, roles: ['data']});
    assert.equal(result.available, true, `${href} (${type})`);
    assert.equal(result.kind, kind);
  }
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
