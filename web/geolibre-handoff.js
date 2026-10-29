/** Safe, user-initiated deep links into the public GeoLibre Web application. */
import {sanitizedURL} from './fieldwork-handoff.js';

export const GEOLIBRE_WEB_URL = 'https://web.geolibre.app/';

const SUPPORTING_ROLES = new Set(['thumbnail', 'overview', 'metadata']);
const GEOJSON_TYPES = new Set(['application/geo+json', 'application/vnd.geo+json']);
const LIDAR_TYPES = new Set([
  'application/vnd.las', 'application/vnd.laz', 'application/vnd.laszip', 'application/vnd.laszip+copc',
]);
const CREDENTIAL_PARAMETER = /^(?:password|passwd|authorization|auth|auth_token|bearer|bearer_token|credential|secret|jwt|ticket|private_token|session|sessionid|session_id|sessionkey|session_key|session_token|sid)$/i;

function mediaType(value) {
  return typeof value === 'string' ? value.trim().toLowerCase().split(';', 1)[0].trim() : '';
}

function unavailable(reason) { return {available: false, reason}; }

function authenticationDeclared(value) {
  return !Array.isArray(value) || value.length > 0;
}

function credentialQuery(value, base) {
  try { return [...new URL(value, base).searchParams.keys()].some(key => CREDENTIAL_PARAMETER.test(key)); }
  catch { return false; }
}

function isProtectedCopernicus(url) {
  return url.origin === 'https://download.dataspace.copernicus.eu';
}

function format(source, declaredType) {
  const type = mediaType(declaredType), path = source.pathname.toLowerCase();
  if (/netcdf|jpeg2000|jp2/.test(type) || /\.(?:nc|nc4|cdf|jp2|j2k)$/i.test(path)) return null;
  if (path.endsWith('/ept.json') || path === 'ept.json') return {kind: 'ept'};
  if (/\.(?:las|laz)$/i.test(path)) return {kind: 'lidar'};
  if (/\.(?:tif|tiff|cog)$/i.test(path)) return {kind: 'cog'};
  if (/\.(?:parquet|geoparquet)$/i.test(path)) return {kind: 'geoparquet'};
  if (path.endsWith('.pmtiles')) return {kind: 'pmtiles'};
  if (path.endsWith('.geojson')) return {kind: 'geojson'};
  if (path.endsWith('.json') && GEOJSON_TYPES.has(type)) return {kind: 'geojson'};
  const basename = path.split('/').filter(Boolean).at(-1) || '';
  if (!basename || basename.includes('.')) return null;
  if (LIDAR_TYPES.has(type)) return {kind: 'lidar', dataType: 'lidar'};
  if (GEOJSON_TYPES.has(type)) return {kind: 'geojson'};
  return null;
}

function destination(source, dataType) {
  const url = new URL(GEOLIBRE_WEB_URL);
  url.searchParams.set('data', source);
  if (dataType) url.searchParams.set('dataType', dataType);
  return url.href;
}

export function geoLibreAssetHandoff({href, base, type, roles, authRefs = []} = {}) {
  if (roles !== undefined && !Array.isArray(roles)) {
    return unavailable('GeoLibre handoff is unavailable because the asset roles declaration is malformed.');
  }
  const declaredRoles = (roles || []).filter(value => typeof value === 'string').map(value => value.trim().toLowerCase());
  if (declaredRoles.some(role => SUPPORTING_ROLES.has(role))) {
    return unavailable('GeoLibre handoff is unavailable for preview, overview, and metadata assets.');
  }
  if (authenticationDeclared(authRefs)) {
    return unavailable('GeoLibre handoff cannot transfer provider authentication. Use the provider access controls.');
  }
  if (typeof href !== 'string' || !href.trim()) return unavailable('GeoLibre needs a public HTTPS asset address.');
  if (credentialQuery(href, base)) return unavailable('GeoLibre handoff cannot transfer a signed or credential-bearing asset address.');
  let sanitized;
  try { sanitized = sanitizedURL(href, base); }
  catch { return unavailable('GeoLibre needs a public HTTPS asset address.'); }
  if (sanitized.redacted_parameters.length) {
    return unavailable('GeoLibre handoff cannot transfer a signed or credential-bearing asset address.');
  }
  const source = new URL(sanitized.href);
  if (source.protocol !== 'https:') {
    return unavailable('GeoLibre Web needs an HTTPS asset address to avoid browser mixed-content blocking.');
  }
  if (isProtectedCopernicus(source)) {
    return unavailable('GeoLibre handoff cannot transfer the Copernicus session token. Use the provider access controls.');
  }
  const supported = format(source, type);
  if (!supported) return unavailable('GeoLibre Web does not directly support this declared asset format.');
  return {available: true, source: sanitized.href, kind: supported.kind,
    dataType: supported.dataType || null, href: destination(sanitized.href, supported.dataType)};
}
