// Focused browser-client protocol regressions. Uses Node's native Fetch types.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {polygonValue} from '../web/geometry.js';
import {STACClient, PRESETS, dateRange, viewportBBox, fetchJSON, localToday, earliestCollectionDate, collectionBBox, copernicusDownloadAccess} from '../web/stac.js';

const root = {type: 'Catalog', id: 'synthetic', stac_version: '1.0.0', links: [{rel: 'data', href: './collections'}, {rel: 'search', href: './search'}]};
const item = (id, extra = {}) => ({type: 'Feature', id, stac_version: '1.0.0', properties: {}, geometry: null, links: [], assets: {}, ...extra});
const page = (features, links = []) => ({type: 'FeatureCollection', features, links});
const fetcher = handler => async (url, options) => ({ok: true, url, json: async () => structuredClone(await handler(new URL(url), options))});

test('protected Copernicus assets use the official sign-in browser and preserve item paths', () => {
  const api = 'https://stac.dataspace.copernicus.eu/v1/';
  const file = 'https://download.dataspace.copernicus.eu/odata/v1/Products(abc)/Nodes(product)/Nodes(file.tiff)/$value';
  for (const format of ['cog', 'nc']) {
    const path = `collections/clms_ndvi_${format}/items/product_${format}`;
    const record = item(`product_${format}`, {collection: `clms_ndvi_${format}`, links: [{rel: 'self', href: api + path + '?ignore=1#fragment'}]});
    const original = structuredClone(record);
    assert.deepEqual(copernicusDownloadAccess(file, record, 'https://mirror.test/item.json'), {
      browserURL: 'https://browser.stac.dataspace.copernicus.eu/' + path, itemSpecific: true,
    });
    assert.deepEqual(record, original);
    record.links = [];
    assert.equal(copernicusDownloadAccess(file, record, api + 'search').browserURL, 'https://browser.stac.dataspace.copernicus.eu/' + path);
    record.links = [{rel: 'self', href: './product_' + format}];
    assert.equal(copernicusDownloadAccess(file, record, api + path).itemSpecific, true);
  }
  const fallback = {browserURL: 'https://browser.stac.dataspace.copernicus.eu/', itemSpecific: false};
  assert.deepEqual(copernicusDownloadAccess(file, item('unmapped'), 'https://mirror.test/search'), fallback);
  assert.deepEqual(copernicusDownloadAccess(file, item('..', {collection: '..'}), api + 'search'), fallback);
  assert.equal(copernicusDownloadAccess(file.replace('/Nodes(product)/Nodes(file.tiff)/$value', '/$zip'), item('x'), api).itemSpecific, false);
  for (const href of ['https://data.worldpop.org/data.tif', file.replace('download.dataspace.copernicus.eu', 'download.dataspace.copernicus.eu.evil.test'), file.replace('https://', 'https://user:secret@'), 'javascript:alert(1)', 's3://eodata/file.tif']) {
    assert.equal(copernicusDownloadAccess(href, item('x'), api), null);
  }
});

test('simple polygon validation matches shared geometry cases', () => {
  const cases = JSON.parse(readFileSync(new URL('./fixtures/study-geometries.json', import.meta.url)));
  for (const ring of cases.valid) assert.deepEqual(polygonValue({type: 'Polygon', coordinates: [ring]}).coordinates, [ring]);
  for (const ring of cases.invalid) assert.throws(() => polygonValue({type: 'Polygon', coordinates: [ring]}));
  for (const invalid of [null, {}, {type: 'MultiPolygon', coordinates: []}, {type: 'Polygon', coordinates: [cases.valid[0], cases.valid[0]]}, {type: 'Polygon', coordinates: [[[NaN, 1], [0, 0], [1, 0], [NaN, 1]]]}]) assert.throws(() => polygonValue(invalid));
  for (const count of [500, 501]) {
    const ring = Array.from({length: count}, (_, i) => [30 + Math.cos(2 * Math.PI * i / count), Math.sin(2 * Math.PI * i / count)]);
    const polygon = {type: 'Polygon', coordinates: [[...ring, [...ring[0]]]]};
    if (count === 500) assert.deepEqual(polygonValue(polygon), polygon);
    else assert.throws(() => polygonValue(polygon), /3–500/);
  }
});

test('polygons prefer advertised POST and capture inputs before awaiting the response', async () => {
  let complete, entered, request;
  const started = new Promise(resolve => { entered = resolve; });
  const client = new STACClient(fetcher((url, options) => {
    if (url.pathname === '/') return {...root, links: [
      {rel: 'search', href: './get-search', method: 'GET'},
      {rel: 'search', href: './post-search?token=keep&bbox=stale', method: 'POST'},
    ]};
    request = {url, options};
    if (options.method === 'POST') { entered(); return new Promise(resolve => { complete = resolve; }); }
    return page([item('get-result')]);
  }));
  await client.connect('https://fixture.test/');
  const polygon = {type: 'Polygon', coordinates: [[[30, -1], [33, -1], [32, 3], [30, -1]]]};
  const snapshot = {shape: 'polygon', geometry: structuredClone(polygon)};
  const expected = structuredClone(polygon);
  const pending = client.search({intersects: polygon, studyArea: snapshot});
  await started;
  polygon.coordinates[0][0][0] = 99;
  snapshot.geometry.coordinates[0][1][0] = 99;
  complete(page([item('post-result')]));
  await pending;
  assert.equal(request.url.pathname, '/post-search');
  assert.deepEqual(Object.fromEntries(request.url.searchParams), {token: 'keep'});
  assert.deepEqual(JSON.parse(request.options.body).intersects, expected);
  assert.deepEqual(client.provenance().query.intersects, expected);
  assert.deepEqual(client.provenance().study_area.geometry, expected);
  await client.search({bbox: [30, -1, 33, 3]});
  assert.equal(request.options.method, 'GET');
  assert.equal(request.url.pathname, '/get-search');
});

test('GET and POST use exactly the selected spatial filter; snapshots survive edits and failures', async () => {
  const polygon = {type: 'Polygon', coordinates: [[[30, -1], [33, -1], [32, 3], [30, -1]]]};
  for (const method of ['GET', 'POST']) {
    let failure = false, calls = 0, request;
    const client = new STACClient(fetcher((url, options) => {
      calls++;
      if (url.pathname === '/') return {...root, links: [{rel: 'search', method, href: './search?bbox=old&intersects=old&token=keep'}]};
      if (failure) throw new Error('provider outage');
      request = {url, body: options.body ? JSON.parse(options.body) : null};
      return page([item('one')]);
    }));
    await client.connect('https://fixture.test/');
    for (const [mode, spatial] of [['bbox', {bbox: [-180, -90, 180, 90]}], ['polygon', {intersects: polygon}], ['none', {}]]) {
      const snapshot = {shape: 'polygon', geometry: structuredClone(polygon), bbox: [30, -1, 33, 3]};
      await client.search({...spatial, collection: 'TEST', start: '2024-01-01', limit: 2, studyArea: snapshot});
      const sent = method === 'POST' ? request.body : Object.fromEntries(request.url.searchParams);
      if (method === 'POST') assert.deepEqual(Object.fromEntries(request.url.searchParams), {token: 'keep'});
      assert.equal('bbox' in sent, mode === 'bbox');
      assert.equal('intersects' in sent, mode === 'polygon');
      if (mode === 'polygon') assert.deepEqual(method === 'POST' ? sent.intersects : JSON.parse(sent.intersects), polygon);
      assert.ok(sent.collections && sent.datetime && sent.limit);
      assert.equal(client.provenance().spatial_mode, mode);
      snapshot.geometry.coordinates[0][0][0] = 10;
      assert.equal(client.provenance().study_area.geometry.coordinates[0][0][0], 30);
      const previous = client.provenance(); failure = true;
      await assert.rejects(client.search({intersects: polygon}));
      assert.deepEqual(client.provenance(), previous); failure = false;
    }
    const before = calls;
    await assert.rejects(client.search({bbox: [0, 0, 1, 1], intersects: polygon}), /never both/);
    await assert.rejects(client.search({intersects: {type: 'Polygon', coordinates: []}}));
    assert.equal(calls, before);
  }
});

test('Copernicus requests a bounded collection list and preserves provider pagination', async () => {
  const endpoint = 'https://stac.dataspace.copernicus.eu/v1';
  assert.equal(PRESETS.copernicus[1], endpoint);
  const calls = [];
  const client = new STACClient(fetcher(url => {
    calls.push(url.href);
    if (url.href === endpoint) return {...root, links: [{rel: 'data', href: endpoint + '/collections'}]};
    if (url.href === endpoint + '/collections?limit=1000') return {collections: [{id: 'sentinel-2-l2a'}], links: [{rel: 'next', href: './collections?offset=1&limit=1'}]};
    assert.equal(url.href, endpoint + '/collections?offset=1&limit=1');
    return {collections: [{id: 'sentinel-1-grd'}], links: []};
  }));
  await client.connect(PRESETS.copernicus[1]);
  assert.equal(calls.length, 2);
  await client.moreCollections();
  assert.deepEqual(client.collections.map(c => c.id), ['sentinel-2-l2a', 'sentinel-1-grd']);
  assert.equal(client.collectionNext, null);
  for (const advertised of [endpoint + '/collections?limit=5', 'https://fixture.test/collections']) {
    const other = new STACClient(fetcher(url => {
      if (url.href === endpoint) return {...root, links: [{rel: 'data', href: advertised}]};
      assert.equal(url.href, advertised);
      return {collections: [], links: []};
    }));
    await other.connect(endpoint);
  }
});

test('collection bounds use the overall extent and discard only elevation axes', () => {
  const collection = bbox => ({extent: {spatial: {bbox}}});
  const bounds = [29.123456789, -2, 35.987654321, 5];
  assert.deepEqual(collectionBBox(collection([bounds, [30, 0, 31, 1], [32, 2, 33, 3]])), bounds);
  assert.deepEqual(collectionBBox(collection([[-123, 37, 100, -121, 39, 900]])), [-123, 37, -121, 39]);
  assert.deepEqual(collectionBBox(collection([[170, -10, -170, 10]])), [170, -10, -170, 10]);
  assert.deepEqual(collectionBBox(collection([[-180, -90, 180, 90]])), [-180, -90, 180, 90]);
  assert.deepEqual(collectionBBox(collection([[30, 0, 30, 0]])), [30, 0, 30, 0]);
  assert.deepEqual(collectionBBox(collection([[30, 0, 30, 2]])), [30, 0, 30, 2]);
  assert.deepEqual(collectionBBox(collection([[30, 0, 32, 0]])), [30, 0, 32, 0]);
  assert.deepEqual(collectionBBox(collection([[180, 0, -180, 1]])), [180, 0, -180, 1]);
  for (const bbox of [[], {}, [[0, 1, 2]], [[0, 2, 1, 0]],
    [[-181, 0, 1, 2]], [[0, -91, 1, 2]], [[0, 0, 181, 2]], [[0, 0, 1, 91]],
    [[-123, 37, 900, -121, 39, 100]], [[0, 0, NaN, 1]], [['0', 0, 1, 1]]]) {
    assert.equal(collectionBBox(collection(bbox)), null);
  }
  assert.equal(collectionBBox({}), null);
  assert.equal(collectionBBox(null), null);
});

test('date defaults use earliest UTC coverage, with 2000 fallback for unavailable starts', () => {
  const collection = intervals => ({extent: {temporal: {interval: intervals}}});
  assert.equal(earliestCollectionDate([collection([['2015-01-01T00:00:00Z', null]])]), '2015-01-01');
  assert.equal(earliestCollectionDate([
    collection([['2020-01-01T00:00:00Z', null], ['2010-05-03T10:00:00Z', null]]),
    collection([['1985-06-01T00:00:00Z', null]]),
  ]), '1985-06-01');
  assert.equal(earliestCollectionDate([collection([['2015-01-01T00:30:00+02:00', null]])]), '2014-12-31');
  for (const collections of [[], [{}], [null], [collection([])], [collection([[null, null]])],
    [collection([['garbage', null]])], [collection([['2023-02-29T00:00:00Z', null]])],
    [collection([['2015-01-01T00:00:00', null]])],
    [collection([[null, null], ['2015-01-01T00:00:00Z', null]])]]) {
    assert.equal(earliestCollectionDate(collections), '2000-01-01');
  }
  // A known future start stays truthful; existing range validation handles From > Until.
  assert.equal(earliestCollectionDate([collection([['2099-01-01T00:00:00Z', null]])]), '2099-01-01');
});

test('today uses local calendar components and pads month/day', () => {
  assert.equal(localToday(new Date(2026, 0, 2, 23, 59)), '2026-01-02');
  assert.equal(localToday(new Date(2026, 9, 8, 0, 1)), '2026-10-08');
});

test('end dates include fractional seconds; wrapped and whole-world viewports', () => {
  assert.equal(dateRange('', '2024-02-29'), '../2024-02-29T23:59:59.999999Z');
  assert.throws(() => viewportBBox(170, -10, 190, 10), /antimeridian/);
  assert.throws(() => viewportBBox(-190, -10, -170, 10), /antimeridian/);
  assert.deepEqual(viewportBBox(-220, -95, 220, 95), [-180, -90, 180, 90]);
  assert.deepEqual(viewportBBox(350, -10, 370, 10), [-10, -10, 10, 10]);
});

test('body-read aborts retain the timeout error instead of becoming non-JSON', async () => {
  const delayedBody = async (_, options) => ({ok: true, json: () => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Body aborted', 'AbortError')));
  })});
  await assert.rejects(fetchJSON({url: 'https://fixture.test/'}, delayedBody, 5), /timed out/);
});

test('GET search replaces advertised filters and discards URL fragments', async () => {
  let searchURL;
  const client = new STACClient(fetcher(url => {
    if (url.pathname === '/') return {...root, links: [{rel: 'search', href: './search?collections=OLD&limit=99&limit=98&datetime=old&token=keep#fragment'}]};
    searchURL = url;
    return page([item(url.searchParams.get('collections'))]);
  }));
  await client.connect('https://fixture.test/');
  await client.search({bbox: [1, 2, 3, 4], collection: 'TEST', start: '2024-02-29', end: '2024-02-29', limit: 2});
  assert.equal(searchURL.hash, '');
  assert.deepEqual(searchURL.searchParams.getAll('limit'), ['2']);
  assert.equal(searchURL.searchParams.get('collections'), 'TEST');
  assert.equal(searchURL.searchParams.get('bbox'), '1,2,3,4');
  assert.equal(searchURL.searchParams.get('datetime'), '2024-02-29T00:00:00Z/2024-02-29T23:59:59.999999Z');
  assert.equal(searchURL.searchParams.get('token'), 'keep');
  assert.equal(client.items[0].id, 'TEST');
});

test('reconnect clears all provider state and only commits complete initialization', async () => {
  let mode = 'api', calls = 0;
  const client = new STACClient(fetcher(url => {
    calls++;
    if (url.pathname === '/') return mode === 'static' ? {...root, id: 'new-static', links: []} : root;
    if (url.pathname === '/collections') {
      if (mode === 'fail') throw new Error('collections outage');
      return {collections: [{id: 'TEST'}], links: [{rel: 'next', href: './collections2'}]};
    }
    return page([item('first')], [{rel: 'next', href: './page2'}]);
  }));
  await client.connect('https://fixture.test/');
  await client.search({bbox: [0, 0, 1, 1]});
  assert.ok(client.next && client.collectionNext && client.retrievedAt);
  mode = 'static';
  await client.connect('https://fixture.test/');
  assert.equal(client.root.id, 'new-static');
  assert.deepEqual(client.items, []);
  assert.deepEqual(client.collections, []);
  assert.deepEqual(client.history, []);
  for (const value of [client.next, client.collectionNext, client.query, client.retrievedAt]) assert.equal(value, null);
  mode = 'api';
  await client.connect('https://fixture.test/');
  await client.search({bbox: [0, 0, 1, 1]});
  mode = 'fail';
  await assert.rejects(client.connect('https://fixture.test/'));
  assert.equal(client.root, null);
  assert.equal(client.url, null);
  assert.deepEqual(client.items, []);
  assert.deepEqual(client.collections, []);
  assert.deepEqual(client.history, []);
  for (const value of [client.next, client.collectionNext, client.query, client.retrievedAt, client.searchLink]) assert.equal(value, null);
  const before = calls;
  await client.more(); await client.moreCollections();
  assert.equal(calls, before);
});

test('collection deduplication precedes the initial limit and ignores invalid IDs', async () => {
  const client = new STACClient(fetcher(url => url.pathname === '/' ? {...root, links: [null, ...root.links]} : {
    collections: [null, {}, {id: ''}, ...Array.from({length: 1001}, () => ({id: 'SAME'})), {id: 'OTHER'}], links: [null],
  }));
  await client.connect('https://fixture.test/');
  assert.deepEqual(client.collections.map(c => c.id), ['SAME', 'OTHER']);
});

test('dedup keys preserve distinct slash-containing collection/item pairs', async () => {
  const client = new STACClient(fetcher(url => url.pathname === '/' ? {...root, links: [root.links[1]]} : page([
    null, {}, item('b/c', {collection: 'a'}), item('c', {collection: 'a/b'}), item('b/c', {collection: 'a'}),
  ])));
  await client.connect('https://fixture.test/');
  await client.search({bbox: [0, 0, 1, 1]});
  assert.deepEqual(client.items.map(i => [i.collection, i.id]), [['a', 'b/c'], ['a/b', 'c']]);
});

test('exports keep original metadata and resolve each page base and relative self exactly once', async () => {
  const first = item('self', {links: [null, {rel: 'self', href: './items/x.json'}, {rel: 'about', href: './about.json'}], assets: {data: {href: './data.tif'}, invalid: null}});
  const second = item('no-self', {links: [{rel: 'about', href: './about.json'}], assets: {data: {href: './data.tif'}}});
  const client = new STACClient(fetcher(url => {
    if (url.pathname === '/root.json') return {...root, links: [{rel: 'search', href: './one/search'}]};
    if (url.pathname === '/one/search') return page([null, first, second], [null, {rel: 'next', href: '../two/search'}]);
    return page([item('page-two', {assets: {data: {href: './data.tif'}}})]);
  }));
  await client.connect('https://fixture.test/root.json');
  await client.search({bbox: [0, 0, 1, 1]});
  const firstTime = client.provenance().retrieved_at;
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(client.provenance().retrieved_at, firstTime);
  await client.more();
  const lastTime = client.provenance().retrieved_at;
  assert.notEqual(lastTime, firstTime);
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(client.provenance().retrieved_at, lastTime);
  const exported = client.geojson().features;
  assert.equal(exported[0].links[1].href, 'https://fixture.test/one/items/x.json');
  assert.equal(client.linkURL(client.items[0], client.items[0].links[1]), 'https://fixture.test/one/items/x.json');
  assert.equal(exported[0].links[2].href, 'https://fixture.test/one/items/about.json');
  assert.equal(exported[0].assets.data.href, 'https://fixture.test/one/items/data.tif');
  assert.equal(exported[1].assets.data.href, 'https://fixture.test/one/data.tif');
  assert.equal(exported[2].assets.data.href, 'https://fixture.test/two/data.tif');
  assert.deepEqual(client.items[0], first);
  assert.deepEqual(client.items[1], second);
  exported[0].properties.changed = true;
  assert.deepEqual(client.items[0].properties, {});
});

test('static item acquisition sets a stable timestamp and portable export', async () => {
  const client = new STACClient(fetcher(url => url.pathname === '/root.json' ? {...root, links: []} : item('static', {assets: {data: {href: './data.tif'}}})));
  await client.connect('https://fixture.test/root.json');
  await client.openItem({href: './items/static.json'});
  const retrieved = client.provenance().retrieved_at;
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.ok(retrieved);
  assert.equal(client.provenance().retrieved_at, retrieved);
  assert.equal(client.geojson().features[0].assets.data.href, 'https://fixture.test/items/data.tif');
});


// Both implementations consume these same normalization fixtures.
import {normalizeCatalogs, normalizeSnapshot, filterCatalogs, endpointProblem, refreshDirectory, DIRECTORY_API} from '../web/catalog-directory.js';
const directoryCases = JSON.parse(readFileSync(new URL('./fixtures/catalog-directory.json', import.meta.url)));
test('directory normalization preserves advertised records and excludes protected listings', () => {
  for (const c of directoryCases.normalization) {
    if (c.ids) {
      const rows = normalizeCatalogs(c.input);
      assert.deepEqual(rows.map(row => row.id), c.ids, c.name);
      for (const row of rows) {
        assert.equal(row.url, c.input.find(original => original.id === row.id).url);
        assert.deepEqual(Object.keys(row), ['id', 'slug', 'title', 'url', 'access', 'isApi']);
      }
      for (const filter of c.filters || []) assert.deepEqual(filterCatalogs(rows, filter.term).map(row => row.id), filter.ids);
    } else assert.throws(() => normalizeCatalogs(c.input), undefined, c.name);
  }
  for (const c of directoryCases.endpoints) assert.equal(!endpointProblem(c.url), c.supported, c.url);
  const snapshot = JSON.parse(readFileSync(new URL('../web/public-catalogs.json', import.meta.url)));
  assert.deepEqual(normalizeSnapshot(snapshot), snapshot);
  assert.throws(() => normalizeSnapshot({...snapshot, api: 'https://unsafe.test'}));
  assert.throws(() => normalizeSnapshot({...snapshot, fetched_at: 'invalid'}));
});
test('live directory refresh validates and omits credentials', async () => {
  const refreshed = await refreshDirectory(async (url, options) => {
    assert.equal(url, DIRECTORY_API);
    assert.equal(options.credentials, 'omit');
    return {ok: true, json: async () => directoryCases.normalization[0].input};
  });
  assert.deepEqual(refreshed.catalogs.map(c => c.id), [3, 2, 1]);
  await assert.rejects(refreshDirectory(async () => ({ok: false, status: 503})), /HTTP 503/);
  await assert.rejects(refreshDirectory(async () => ({ok: true, json: async () => {throw Error('html');}})), /non-JSON/);
  await assert.rejects(refreshDirectory(async () => ({ok: true, json: async () => [{access: 'public'}]})), /Invalid public/);
});

test('Digital Earth Africa uses the documented endpoint and explicit bounded search', async () => {
  const endpoint = 'https://explorer.digitalearth.africa/stac/';
  assert.equal(PRESETS.deafrica[1], endpoint);
  const calls = [];
  const client = new STACClient(fetcher(url => {
    calls.push(url.href);
    if (url.pathname === '/stac/') return root;
    if (url.pathname === '/stac/collections') return {collections: [{id: 's2_l2a'}], links: []};
    return page([]);
  }));
  await client.connect(endpoint);
  await client.search({collection: 's2_l2a', bbox: [45, -20.1, 47, -19.8], start: '2020-01-01', end: '2020-01-31', limit: 3});
  assert.equal(calls[0], endpoint);
  assert.deepEqual(Object.fromEntries(new URL(calls.at(-1)).searchParams), {collections: 's2_l2a', bbox: '45,-20.1,47,-19.8', limit: '3', datetime: '2020-01-01T00:00:00Z/2020-01-31T23:59:59.999999Z'});
});
