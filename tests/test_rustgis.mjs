import assert from 'node:assert/strict';
import test from 'node:test';
import {RUSTGIS_WEB_URL, rustGISAssetHandoff, rustGISItemHandoff} from '../web/rustgis-handoff.js';

test('builds exact public asset and Item handoffs', () => {
  const asset = rustGISAssetHandoff({href: './data.tif', base: 'https://catalog.test/items/one.json', type: 'image/tiff', roles: ['data']});
  assert.equal(asset.available, true);
  const assetTarget = new URL(asset.href);
  assert.equal(assetTarget.origin + '/', RUSTGIS_WEB_URL);
  assert.equal(assetTarget.searchParams.has('blank'), true);
  assert.equal(assetTarget.searchParams.get('data'), 'https://catalog.test/items/data.tif');

  const item = rustGISItemHandoff({href: './one.json', base: 'https://catalog.test/items/', type: 'application/geo+json'});
  assert.equal(item.available, true);
  assert.equal(new URL(item.href).searchParams.get('stac'), 'https://catalog.test/items/one.json');
});

test('accepts verified RustGIS Web formats and refuses unsupported formats', () => {
  const mediaTypes = [
    'application/geo+json', 'application/vnd.geo+json', 'text/csv; charset=utf-8', 'application/csv',
    'text/tab-separated-values', 'application/vnd.apache.parquet', 'application/x-parquet',
    'application/flatgeobuf', 'application/vnd.flatgeobuf', 'application/geopackage+sqlite3',
    'application/vnd.google-earth.kml+xml', 'application/vnd.google-earth.kmz', 'application/gpx+xml',
    'application/vnd.pmtiles', 'application/vnd.las', 'application/vnd.laz', 'application/vnd.shp+zip',
    'image/tiff', 'image/geotiff', 'application/geotiff', 'application/x-geotiff',
    'text/plain ; profile = "esri-ascii-grid"',
  ];
  for (const type of mediaTypes) {
    assert.equal(rustGISAssetHandoff({href: 'https://data.test/extensionless', type, roles: ['data']}).available, true, type);
  }
  for (const extension of [
    '.tif', '.tiff', '.geojson', '.json', '.csv', '.tsv', '.parquet', '.fgb', '.gpkg', '.kml', '.kmz',
    '.gpx', '.pmtiles', '.las', '.laz', '.asc', '.shp.zip', '.shapefile.zip',
  ]) {
    const href = `https://data.test/map${extension}`;
    assert.equal(rustGISAssetHandoff({href, type: 'application/octet-stream', roles: ['data']}).available, true, href);
  }

  for (const [href, type] of [
    ['https://data.test/data.nc', 'application/x-netcdf'],
    ['https://data.test/image.jp2', 'image/jp2'],
    ['https://data.test/archive.zip', 'application/zip'],
    ['https://data.test/readme.xml', 'application/xml'],
  ]) assert.equal(rustGISAssetHandoff({href, type, roles: ['data']}).available, false, href);
});

test('refuses supporting, authenticated, signed, credential-bearing and protected inputs', () => {
  for (const role of ['thumbnail', 'overview', 'metadata']) {
    assert.match(rustGISAssetHandoff({href: 'https://data.test/supporting.tif', type: 'image/tiff', roles: [role]}).reason, /preview/);
  }
  assert.match(rustGISAssetHandoff({href: 'https://data.test/data.tif', type: 'image/tiff', authRefs: ['oidc']}).reason, /authentication/);
  assert.match(rustGISAssetHandoff({href: 'https://data.test/data.tif', type: 'image/tiff', authRefs: 'oidc'}).reason, /authentication/);
  assert.match(rustGISAssetHandoff({href: ' ', base: 'https://data.test/item.json', type: 'image/tiff'}).reason, /public HTTP/);
  assert.match(rustGISAssetHandoff({href: 'https://data.test/data.tif?X-Amz-Signature=secret', type: 'image/tiff'}).reason, /signed/);
  assert.match(rustGISAssetHandoff({href: 'https://user:secret@data.test/data.tif', type: 'image/tiff'}).reason, /public HTTP/);
  for (const suffix of ['$value', '%24value']) assert.match(rustGISAssetHandoff({
    href: `https://download.dataspace.copernicus.eu/odata/v1/Products(id)/Nodes(file.tif)/${suffix}`, type: 'image/tiff',
  }).reason, /Copernicus session token/);
  for (const key of ['password', 'authorization', 'auth', 'bearer', 'credential', 'secret', 'jwt', 'ticket', 'session']) {
    assert.match(rustGISAssetHandoff({href: `https://data.test/data.tif?${key}=hidden`, type: 'image/tiff'}).reason, /credential-bearing/, key);
  }
  assert.equal(rustGISItemHandoff({href: 'https://catalog.test/item.json?token=secret'}).available, false);
  assert.equal(rustGISItemHandoff({href: 'https://catalog.test/item.json', authRefs: ['oidc']}).available, false);
  assert.equal(rustGISItemHandoff({href: 'https://catalog.test/item.json', authRefs: 'oidc'}).available, false);
  assert.equal(rustGISItemHandoff({href: ' ', base: 'https://catalog.test/item.json'}).available, false);
  assert.equal(rustGISItemHandoff({href: 'https://catalog.test/item.html', type: 'text/html'}).available, false);
});

test('never embeds rejected secrets in a destination URL', () => {
  for (const result of [
    rustGISAssetHandoff({href: 'https://data.test/data.tif?sig=secret', type: 'image/tiff'}),
    rustGISAssetHandoff({href: 'https://user:secret@data.test/data.tif', type: 'image/tiff'}),
    rustGISItemHandoff({href: 'https://catalog.test/item.json?access_token=secret'}),
  ]) {
    assert.equal(result.available, false);
    assert.equal('href' in result, false);
    assert.doesNotMatch(JSON.stringify(result), /secret/);
  }
});
