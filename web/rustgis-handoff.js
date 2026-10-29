/** Safe, user-initiated deep links into the public RustGIS Web application. */
import {sanitizedURL} from './fieldwork-handoff.js';

export const RUSTGIS_WEB_URL = 'https://web.rustgis.app/';

const SUPPORTING_ROLES = new Set(['thumbnail', 'overview', 'metadata']);
const SUPPORTED_MEDIA_TYPES = new Set([
  'application/geo+json', 'application/vnd.geo+json',
  'text/csv', 'application/csv', 'text/tab-separated-values',
  'application/vnd.apache.parquet', 'application/x-parquet',
  'application/flatgeobuf', 'application/vnd.flatgeobuf',
  'application/geopackage+sqlite3',
  'application/vnd.google-earth.kml+xml', 'application/vnd.google-earth.kmz',
  'application/gpx+xml', 'application/vnd.pmtiles',
  'application/vnd.las', 'application/vnd.laz', 'application/vnd.shp+zip',
  'image/tiff', 'image/geotiff', 'application/geotiff', 'application/x-geotiff',
  'text/plain; profile=esri-ascii-grid',
]);
const SUPPORTED_EXTENSIONS = [
  '.tif', '.tiff', '.geojson', '.json', '.csv', '.tsv', '.parquet', '.fgb', '.gpkg',
  '.kml', '.kmz', '.gpx', '.pmtiles', '.las', '.laz', '.asc', '.shp.zip', '.shapefile.zip',
];
const CREDENTIAL_PARAMETER = /^(?:password|passwd|authorization|auth|bearer|credential|secret|jwt|ticket|session|sessionid|session_id)$/i;

function mediaType(value) {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : '';
  const [essence, ...parameters] = normalized.split(';').map(part => part.trim());
  if (essence === 'text/plain' && parameters.some(parameter => /^profile\s*=\s*["']?esri-ascii-grid["']?$/.test(parameter))) {
    return 'text/plain; profile=esri-ascii-grid';
  }
  return essence;
}

function isProtectedCopernicus(url) {
  return url.origin === 'https://download.dataspace.copernicus.eu';
}

function supportedAsset(url, declaredType) {
  const type = mediaType(declaredType);
  if (/netcdf|jpeg2000|jp2/.test(type) || /\.(?:nc|nc4|cdf|jp2|j2k)$/i.test(url.pathname)) return false;
  if (SUPPORTED_MEDIA_TYPES.has(type)) return true;
  const path = url.pathname.toLowerCase();
  return SUPPORTED_EXTENSIONS.some(extension => path.endsWith(extension));
}

function destination(parameter, value) {
  const url = new URL(RUSTGIS_WEB_URL);
  url.searchParams.set('blank', '');
  url.searchParams.set(parameter, value);
  return url.href;
}

function unavailable(reason) { return {available: false, reason}; }

function authenticationDeclared(value) {
  return !Array.isArray(value) || value.length > 0;
}

function credentialQuery(value, base) {
  try { return [...new URL(value, base).searchParams.keys()].some(key => CREDENTIAL_PARAMETER.test(key)); }
  catch { return false; }
}

export function rustGISAssetHandoff({href, base, type, roles = [], authRefs = []} = {}) {
  const declaredRoles = Array.isArray(roles) ? roles.filter(value => typeof value === 'string') : [];
  if (declaredRoles.some(role => SUPPORTING_ROLES.has(role))) {
    return unavailable('RustGIS handoff is unavailable for preview, overview, and metadata assets.');
  }
  if (authenticationDeclared(authRefs)) {
    return unavailable('RustGIS handoff cannot transfer provider authentication. Use the provider access controls.');
  }
  if (typeof href !== 'string' || !href.trim()) return unavailable('RustGIS needs a public HTTP(S) asset address.');
  if (credentialQuery(href, base)) return unavailable('RustGIS handoff cannot transfer a signed or credential-bearing asset address.');
  let sanitized;
  try { sanitized = sanitizedURL(href, base); }
  catch { return unavailable('RustGIS needs a public HTTP(S) asset address.'); }
  if (sanitized.redacted_parameters.length) {
    return unavailable('RustGIS handoff cannot transfer a signed or credential-bearing asset address.');
  }
  const source = new URL(sanitized.href);
  if (isProtectedCopernicus(source)) {
    return unavailable('RustGIS handoff cannot transfer the Copernicus session token. Use the provider access controls.');
  }
  if (!supportedAsset(source, type)) {
    return unavailable('RustGIS Web does not directly support this declared asset format.');
  }
  return {available: true, source: sanitized.href, href: destination('data', sanitized.href)};
}

export function rustGISItemHandoff({href, base, type, authRefs = []} = {}) {
  if (authenticationDeclared(authRefs)) return unavailable('RustGIS handoff cannot transfer provider authentication.');
  const declaredType = mediaType(type);
  if (declaredType && !/^(?:application\/(?:[^\s/;]+\+)?json)$/.test(declaredType)) {
    return unavailable('RustGIS needs a STAC Item JSON address.');
  }
  if (typeof href !== 'string' || !href.trim()) return unavailable('RustGIS needs a public STAC Item address.');
  if (credentialQuery(href, base)) return unavailable('RustGIS handoff cannot transfer a signed or credential-bearing Item address.');
  let sanitized;
  try { sanitized = sanitizedURL(href, base); }
  catch { return unavailable('RustGIS needs a public STAC Item address.'); }
  if (sanitized.redacted_parameters.length) {
    return unavailable('RustGIS handoff cannot transfer a signed or credential-bearing Item address.');
  }
  return {available: true, source: sanitized.href, href: destination('stac', sanitized.href)};
}
