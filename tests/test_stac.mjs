// Focused browser-client protocol regressions. Uses Node's native Fetch types.
import test from 'node:test';
import assert from 'node:assert/strict';
import {STACClient, PRESETS, dateRange, viewportBBox, fetchJSON, localToday, earliestCollectionDate, collectionBBox} from '../web/stac.js';

const root = {type: 'Catalog', id: 'synthetic', stac_version: '1.0.0', links: [{rel: 'data', href: './collections'}, {rel: 'search', href: './search'}]};
const item = (id, extra = {}) => ({type: 'Feature', id, stac_version: '1.0.0', properties: {}, geometry: null, links: [], assets: {}, ...extra});
const page = (features, links = []) => ({type: 'FeatureCollection', features, links});
const fetcher = handler => async (url, options) => ({ok: true, url, json: async () => structuredClone(await handler(new URL(url), options))});

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
