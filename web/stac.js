/** Browser-native STAC protocol. No proxy, credentials, or raster downloads. */
export const PRESETS = {
  worldpop: ['WorldPop', 'https://api.stac.worldpop.org'],
  earthsearch: ['Earth Search', 'https://earth-search.aws.element84.com/v1'],
  planetary: ['Planetary Computer', 'https://planetarycomputer.microsoft.com/api/stac/v1'],
};
export const MAX_ITEMS = 500;

export function safeURL(value, base, httpsOnly = false) {
  const url = new URL(value, base);
  if (!(httpsOnly ? ['https:'] : ['https:', 'http:']).includes(url.protocol) || url.username || url.password) {
    throw new Error(httpsOnly ? 'Use an HTTPS URL without credentials.' : 'Only HTTP(S) links without credentials are allowed.');
  }
  return url.href;
}

export function bboxValue(values) {
  const bbox = typeof values === 'string' ? values.split(',').map(v => v.trim() === '' ? NaN : Number(v)) : values;
  if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(Number.isFinite) ||
      bbox[0] < -180 || bbox[2] > 180 || bbox[1] < -90 || bbox[3] > 90 || bbox[0] >= bbox[2] || bbox[1] >= bbox[3]) {
    throw new Error('Bbox must be west, south, east, north within ±180°/±90°, with west < east and south < north. Split antimeridian searches.');
  }
  return bbox;
}

export function viewportBBox(west, south, east, north) {
  const width = east - west;
  south = Math.max(-90, south); north = Math.min(90, north);
  if (width >= 360) return bboxValue([-180, south, 180, north]);
  const normalizedWest = ((west + 180) % 360 + 360) % 360 - 180;
  if (width <= 0 || normalizedWest + width > 180) {
    throw new Error('This viewport crosses the antimeridian. Split it into two searches on either side of ±180°.');
  }
  return bboxValue([normalizedWest, south, normalizedWest + width, north]);
}

export function dateRange(start = '', end = '') {
  for (const value of [start, end]) {
    if (value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value)) {
      throw new Error('Dates must be real calendar dates in YYYY-MM-DD format.');
    }
  }
  if (start && end && start > end) throw new Error('Start date must be before or equal to end date.');
  return start || end ? `${start ? start + 'T00:00:00Z' : '..'}/${end ? end + 'T23:59:59.999999Z' : '..'}` : undefined;
}

export function localToday(now = new Date()) {
  return [now.getFullYear(), now.getMonth() + 1, now.getDate()].map((n, i) => String(n).padStart(i ? 2 : 4, '0')).join('-');
}

export function earliestCollectionDate(collections) {
  const fallback = '2000-01-01';
  const starts = [];
  for (const collection of collections) {
    const intervals = collection?.extent?.temporal?.interval;
    if (!Array.isArray(intervals) || !intervals.length) return fallback;
    for (const interval of intervals) {
      const start = Array.isArray(interval) ? interval[0] : null;
      // Use the requested default when metadata cannot provide a start date.
      if (typeof start !== 'string' || !/^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$/.test(start) || !Number.isFinite(Date.parse(start))) return fallback;
      try { dateRange(start.slice(0, 10)); } catch { return fallback; }
      starts.push(new Date(start).toISOString().slice(0, 10));
    }
  }
  return starts.sort()[0] || fallback;
}

export function nextRequest(link, previous) {
  const url = safeURL(link.href, previous.url, true);
  const method = (link.method || 'GET').toUpperCase();
  if (!['GET', 'POST'].includes(method)) throw new Error('Only GET and POST pagination are supported.');
  return {url, method, ...(method === 'POST' ? {body: link.merge ? {...(previous.body || {}), ...(link.body || {})} : (link.body || {})} : {})};
}

export async function fetchJSON(request, fetcher = fetch, timeout = 20000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetcher(request.url, {
      method: request.method || 'GET', signal: controller.signal, credentials: 'omit',
      headers: {Accept: 'application/geo+json, application/json', ...(request.body ? {'Content-Type': 'application/json'} : {})},
      ...(request.body ? {body: JSON.stringify(request.body)} : {}),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status} from provider. Retry later or choose another catalog.`);
    try { return {data: await response.json(), url: response.url || request.url}; }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new Error('Provider returned non-JSON content; use a STAC JSON root URL.');
    }
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Request timed out after 20 seconds. Retry or narrow the query.');
    if (error instanceof TypeError) throw new Error('Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS.');
    throw error;
  } finally { clearTimeout(timer); }
}

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const validItem = item => record(item) && item.type === 'Feature' && ['string', 'number'].includes(typeof item.id);
const itemKey = item => JSON.stringify([typeof item.collection === 'string' ? item.collection : '', item.id]);
function links(doc, rel) {
  return (Array.isArray(doc?.links) ? doc.links : []).filter(link => record(link) && (!rel || link.rel === rel) && typeof link.href === 'string');
}
function uniqueCollections(collections) {
  return [...new Map(collections.filter(c => record(c) && typeof c.id === 'string' && c.id.length).map(c => [c.id, c])).values()].slice(0, 1000);
}
function validRoot(doc) {
  if (!doc || !['Catalog', 'Collection'].includes(doc.type) || typeof doc.stac_version !== 'string' || !Array.isArray(doc.links)) {
    throw new Error('This is not a STAC Catalog or Collection document.');
  }
}

export class STACClient {
  constructor(fetcher = fetch) { this.fetcher = fetcher; this.reset(); }
  reset() {
    this.root = null; this.url = null; this.searchLink = null; this.collections = []; this.collectionNext = null;
    this.items = []; this.history = []; this.next = null; this.query = null; this.retrievedAt = null;
    this.itemLocations = new WeakMap();
  }
  baseFor(item) { return this.itemLocations.get(item)?.base || this.url; }
  linkURL(item, link) {
    return safeURL(link.href, link.rel === 'self' ? this.itemLocations.get(item)?.source || this.url : this.baseFor(item));
  }
  rememberBase(item, url) {
    const self = links(item, 'self')[0];
    let base = url;
    try { if (self) base = safeURL(self.href, url); } catch { /* Retain the response base if self is unsafe. */ }
    this.itemLocations.set(item, {base, source: url});
  }
  async request(req) { return fetchJSON(req, this.fetcher); }
  async connect(url) {
    this.reset();
    const request = {url: safeURL(url, undefined, true), method: 'GET'};
    const result = await this.request(request);
    validRoot(result.data);
    const root = result.data, rootURL = result.url;
    const searchLink = links(root, 'search').find(l => String(l.method || 'GET').toUpperCase() === 'GET') || links(root, 'search').find(l => String(l.method).toUpperCase() === 'POST');
    let collections = uniqueCollections(root.type === 'Collection' ? [root] : []), collectionNext = null;
    const collectionLink = links(root, 'data').find(l => !l.type || (typeof l.type === 'string' && l.type.includes('json')));
    if (collectionLink) {
      const req = {url: safeURL(collectionLink.href, rootURL, true), method: 'GET'};
      const result = await this.request(req);
      if (!Array.isArray(result.data?.collections)) throw new Error('The advertised collections link did not return a collections array.');
      collections = uniqueCollections(result.data.collections);
      collectionNext = collections.length < 1000 && links(result.data, 'next')[0] ? nextRequest(links(result.data, 'next')[0], {...req, url: result.url}) : null;
    }
    Object.assign(this, {root, url: rootURL, searchLink, collections, collectionNext});
    return this.root;
  }
  async moreCollections() {
    if (!this.collectionNext || this.collections.length >= 1000) return;
    const req = this.collectionNext, result = await this.request(req);
    if (!Array.isArray(result.data?.collections)) throw new Error('Invalid collections page.');
    const collections = uniqueCollections([...this.collections, ...result.data.collections]);
    const collectionNext = collections.length < 1000 && links(result.data, 'next')[0] ? nextRequest(links(result.data, 'next')[0], {...req, url: result.url}) : null;
    Object.assign(this, {collections, collectionNext});
  }
  async search({bbox, collection, start, end, limit = 25}) {
    if (!this.searchLink) throw new Error('Static catalog: remote Item Search is not advertised. Browse child and item links instead.');
    const query = {bbox: bboxValue(bbox), limit: Number(limit)};
    if (!Number.isInteger(query.limit) || query.limit < 1 || query.limit > 100) throw new Error('Page size must be 1–100.');
    if (collection) query.collections = [collection];
    const datetime = dateRange(start, end); if (datetime) query.datetime = datetime;
    const method = (this.searchLink.method || 'GET').toUpperCase();
    const url = new URL(safeURL(this.searchLink.href, this.url, true));
    url.hash = '';
    if (method === 'GET') {
      for (const key of ['bbox', 'collections', 'datetime', 'limit']) url.searchParams.delete(key);
      for (const [k, v] of Object.entries(query)) url.searchParams.set(k, Array.isArray(v) ? v.join(',') : v);
    }
    const req = {url: url.href, method, ...(method === 'POST' ? {body: query} : {})};
    // Commit only after a successful response so failed searches remain retryable.
    await this.page(req, true);
    this.query = query;
    return this.items;
  }
  async page(req, reset = false) {
    const {data, url} = await this.request(req);
    if (data?.type !== 'FeatureCollection' || !Array.isArray(data.features)) throw new Error('Search response is not a GeoJSON FeatureCollection.');
    const items = new Map((reset ? [] : this.items).map(item => [itemKey(item), item]));
    for (const item of data.features) {
      if (!validItem(item)) continue;
      this.rememberBase(item, url);
      items.set(itemKey(item), item);
      if (items.size >= MAX_ITEMS) break;
    }
    const link = links(data, 'next')[0];
    this.next = link && items.size < MAX_ITEMS ? nextRequest(link, {...req, url}) : null;
    this.items = [...items.values()];
    this.history = [...(reset ? [] : this.history), req];
    this.retrievedAt = new Date().toISOString();
  }
  async more() { if (this.next) await this.page(this.next); return this.items; }
  catalogLinks() { return links(this.root).filter(l => ['child', 'item', 'parent', 'root'].includes(l.rel)).slice(0, 100); }
  async openItem(link) {
    const req = {url: safeURL(link.href, this.url, true), method: 'GET'};
    const {data, url} = await this.request(req);
    if (!validItem(data) || !data.stac_version) throw new Error('Link did not return a STAC Item.');
    this.items = [data]; this.next = null; this.history = [req]; this.query = null;
    this.rememberBase(data, url);
    this.retrievedAt = new Date().toISOString();
    return data;
  }
  geojson() {
    return {type: 'FeatureCollection', features: this.items.map(item => {
      const copy = structuredClone(item);
      for (const link of links(copy)) {
        try { link.href = this.linkURL(item, link); } catch { /* Preserve unsupported source metadata verbatim. */ }
      }
      for (const asset of Object.values(record(copy.assets) ? copy.assets : {})) {
        if (record(asset) && typeof asset.href === 'string') {
          try { asset.href = safeURL(asset.href, this.baseFor(item)); } catch { /* Preserve unsupported source metadata verbatim. */ }
        }
      }
      return copy;
    })};
  }
  provenance() { return {stac_root: this.url, query: this.query, requests: this.history, retrieved_at: this.retrievedAt, count: this.items.length, max_items: MAX_ITEMS}; }
}
