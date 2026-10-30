import {GEOLIBRE_WEB_URL, geoLibreAssetHandoff} from './geolibre-handoff.js';

const TYPES = new Map([
  ['geojson', 'application/geo+json'],
  ['geoparquet', 'application/vnd.apache.parquet'],
  ['pmtiles', 'application/vnd.pmtiles'],
  ['cog', 'image/tiff'],
  ['lidar', 'application/vnd.laz'],
  ['copc', 'application/vnd.laszip+copc'],
  ['ept', 'application/json'],
]);
const ALLOWED_PARAMETERS = new Set(['data', 'kind']);

export function parseGeoLibreBridgeRequest(search) {
  const params = new URLSearchParams(search);
  if ([...params.keys()].some(key => !ALLOWED_PARAMETERS.has(key)) ||
      params.getAll('data').length !== 1 || params.getAll('kind').length !== 1) {
    throw new Error('The GeoLibre compatibility link is invalid.');
  }
  const source = params.get('data') || '', kind = params.get('kind') || '';
  const type = TYPES.get(kind);
  if (!type) throw new Error('The GeoLibre compatibility link is invalid.');
  const handoff = geoLibreAssetHandoff({href: source, type, roles: ['data']});
  const handoffKind = kind === 'copc' ? 'lidar' : kind;
  if (!handoff.available || handoff.kind !== handoffKind) {
    throw new Error('The GeoLibre compatibility link is invalid.');
  }
  return {source: handoff.source, kind: handoffKind, requiresRange: handoff.requiresRange,
    dataType: handoff.dataType, destination: handoff.href};
}

function header(response, name) {
  const value = response.headers?.get?.(name);
  return typeof value === 'string' ? value.trim() : '';
}

function validContentRange(value) {
  if (!value) return true;
  const match = /^bytes\s+0-0\/(\d+|\*)$/i.exec(value);
  return Boolean(match && (match[1] === '*' || Number(match[1]) >= 1));
}

function rangeFailure(message) {
  return {compatible: false, code: 'range', message};
}

export async function probeGeoLibreAsset(request, {fetchImpl = globalThis.fetch, timeoutMs = 12000} = {}) {
  if (!request || typeof request.source !== 'string' || typeof fetchImpl !== 'function') {
    throw new Error('A valid GeoLibre compatibility request is required.');
  }
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    const response = await fetchImpl(request.source, {
      method: 'GET',
      headers: {Range: 'bytes=0-0'},
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'follow',
      referrerPolicy: 'no-referrer',
      signal: controller.signal,
    });
    response.body?.cancel().catch(() => {});
    if (!response.ok) {
      return {compatible: false, code: 'http',
        message: `The provider returned HTTP ${response.status} to the browser compatibility check.`};
    }
    if (request.requiresRange && response.status !== 206) {
      return rangeFailure('The provider did not honor the one-byte Range request required for remote streaming.');
    }
    if (request.requiresRange && !validContentRange(header(response, 'Content-Range'))) {
      return rangeFailure('The provider returned a Range response for different bytes than requested.');
    }
    if (request.requiresRange && header(response, 'Content-Length') && header(response, 'Content-Length') !== '1') {
      return rangeFailure('The provider returned more than the requested one-byte Range response.');
    }
    const encoding = header(response, 'Content-Encoding').toLowerCase();
    if (request.requiresRange && encoding && encoding !== 'identity') {
      return rangeFailure('The provider encoded the Range response, so byte offsets cannot be verified.');
    }
    if (!request.requiresRange && ![200, 206].includes(response.status)) {
      return {compatible: false, code: 'http',
        message: `The provider returned HTTP ${response.status} without readable dataset bytes.`};
    }
    if (!request.requiresRange && header(response, 'Content-Length') === '0') {
      return {compatible: false, code: 'http', message: 'The provider returned an empty response.'};
    }
    return {compatible: true, code: 'ready', message: 'Browser access is compatible.'};
  } catch {
    if (timedOut) {
      return {compatible: false, code: 'timeout',
        message: 'The provider did not complete the browser compatibility check in time.'};
    }
    return {compatible: false, code: 'network',
      message: 'The browser could not read this provider response. CORS, TLS, or network policy may be blocking it.'};
  } finally {
    clearTimeout(timer);
  }
}

function element(id) { return document.getElementById(id); }

function showFallback(request, result) {
  element('status').textContent = 'Remote browser access could not be verified.';
  element('explanation').textContent = `${result.message} A normal download can still work because file navigation is not subject to the same browser CORS rules.`;
  element('source').textContent = request.source;
  element('download').href = request.source;
  element('try-remote').href = request.destination;
  element('fallback').hidden = false;
  document.body.dataset.state = 'fallback';
}

async function start() {
  let request;
  try { request = parseGeoLibreBridgeRequest(location.search); }
  catch {
    element('status').textContent = 'This GeoLibre compatibility link is invalid.';
    element('explanation').textContent = 'Return to the STAC Explorer and choose the action again. No asset request was sent.';
    element('invalid').hidden = false;
    document.body.dataset.state = 'invalid';
    return;
  }
  element('source').textContent = request.source;
  element('open-geolibre').href = GEOLIBRE_WEB_URL;
  const result = await probeGeoLibreAsset(request);
  if (!result.compatible) {
    showFallback(request, result);
    return;
  }
  element('status').textContent = 'Explorer-origin check passed. Opening this asset in GeoLibre...';
  document.body.dataset.state = 'ready';
  location.replace(request.destination);
}

if (typeof document !== 'undefined') start();
