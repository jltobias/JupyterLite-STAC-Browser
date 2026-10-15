/** Versioned, file-only handoffs for the FieldWork manual import workflow. */
export const SELECTION_PROFILE = 'fieldwork-stac-selection/1';
export const RASTER_PROFILE = 'fieldwork-raster-handoff/1';
export const FIELDWORK_RASTER_LIMITS = Object.freeze({
  crs: 'EPSG:4326', bands: 1, pixel_is_area: true, north_up: true,
  geo_keys: {model_type: 2, raster_type: 1, geographic_type: 4326, angular_units: 9102},
  model_transformation: false, grid_rule: 'finite positive-X/negative-Y grid with consistent ordered CRS84 bounds',
  max_cells: 262144, max_bytes: 5000000,
});

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const secretKey = key => /(?:^|[_:-])(authorization|bearer|token|access[_-]?token|refresh[_-]?token|password|passwd|secret|signature|sig|credential|api[_-]?key|subscription[_-]?key)(?:$|[_:-])/i.test(key);
const sensitiveParameter = key => /^(?:access_token|refresh_token|id_token|oauth_token|oauth_verifier|token|client_id|client_secret|code|code_verifier|assertion|client_assertion|saml_?response|sig|signature|awsaccesskeyid|googleaccessid|expires|policy|key-pair-id|x-amz-.+|x-goog-.+|se|sp|sr|sv|si|sip|spr|srt|ss|st|ses|skoid|sktid|skt|ske|sks|skv|rscc|rscd|rsce|rscl|rsct|key|api_key|apikey|subscription-key)$/i.test(key);

export function sanitizedURL(value, base) {
  let url;
  try { url = new URL(value, base); } catch { throw new Error('The selected asset has no usable HTTP(S) location.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('The selected asset has no usable HTTP(S) location.');
  }
  const redacted_parameters = [];
  for (const key of [...url.searchParams.keys()]) {
    if (sensitiveParameter(key)) { url.searchParams.delete(key); redacted_parameters.push(key); }
  }
  url.hash = '';
  return {href: url.href, redacted_parameters: [...new Set(redacted_parameters)].sort()};
}

function sanitizedReference(value) {
  const absolute = /^[a-z][a-z0-9+.-]*:\/\//i.test(value);
  const relative = /^(?:\.\.?\/|\/)/.test(value) || /^[^\s?#]+\?[^#]*$/.test(value);
  if (!absolute && !relative) return value;
  try {
    if (relative && !value.startsWith('//')) {
      const [withoutFragment] = value.split('#', 1), question = withoutFragment.indexOf('?');
      if (question < 0) return withoutFragment;
      const path = withoutFragment.slice(0, question), parameters = new URLSearchParams(withoutFragment.slice(question + 1));
      for (const key of [...parameters.keys()]) if (sensitiveParameter(key)) parameters.delete(key);
      const query = parameters.toString();
      return path + (query ? `?${query}` : '');
    }
    const url = new URL(value, 'https://relative.invalid/');
    if (url.username || url.password) return '[REDACTED UNSAFE URL]';
    for (const key of [...url.searchParams.keys()]) if (sensitiveParameter(key)) url.searchParams.delete(key);
    url.hash = '';
    return value.startsWith('//') ? url.href.replace(/^https:/, '') : url.href;
  } catch { return '[REDACTED UNSAFE URL]'; }
}

export function sanitizeExport(value, key = '') {
  if (secretKey(key)) return '[REDACTED]';
  if (typeof value === 'string') {
    if (/\bbearer\s+[A-Za-z0-9._~+/=-]+/i.test(value)) return '[REDACTED]';
    if (/^(?:[a-z][a-z0-9+.-]*:\/\/|\.\.?\/|\/)/i.test(value) || /^[^\s?#]+\?[^#]*$/.test(value)) return sanitizedReference(value);
    return value;
  }
  if (Array.isArray(value)) return value.map(entry => sanitizeExport(entry));
  if (record(value)) return Object.fromEntries(Object.entries(value).map(([name, entry]) => [name, sanitizeExport(entry, name)]));
  return value;
}

function utc(value) {
  if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return null;
  return new Date(value).toISOString();
}

export function buildFieldworkSelection({item, assetKey, accessHref, sourceDocument, itemBase, catalog, completedSearch}) {
  if (!record(item) || !record(item.assets) || !Object.prototype.hasOwnProperty.call(item.assets, assetKey) || !record(item.assets[assetKey])) {
    throw new Error('Choose an asset owned by the selected STAC Item.');
  }
  const asset = item.assets[assetKey];
  if (typeof asset.href !== 'string' || !asset.href.trim()) throw new Error('The selected asset has no usable HTTP(S) location.');
  const selectedHref = accessHref || asset.href;
  if (!sourceDocument && (!/^https?:\/\//i.test(asset.href) || !/^https?:\/\//i.test(selectedHref))) throw new Error('A source-document base is required for a relative asset href.');
  const base = itemBase || sourceDocument;
  const resolved = sanitizedURL(selectedHref, base);
  const source = sourceDocument ? sanitizedURL(sourceDocument) : null;
  const sourceBase = sourceDocument ? sanitizedURL(itemBase || sourceDocument) : null;
  const original = sanitizedReference(asset.href);
  const properties = record(item.properties) ? item.properties : {};
  const authRefs = [...new Set([asset, ...Object.values(record(asset.alternate) ? asset.alternate : {})]
    .flatMap(location => Array.isArray(location?.['auth:refs']) ? location['auth:refs'] : []).filter(value => typeof value === 'string'))];
  const studyArea = completedSearch?.study_area ?? null;
  const rawCatalog = catalog ?? completedSearch?.stac_root ?? null;
  const sanitizedAsset = sanitizeExport(asset), sanitizedItem = sanitizeExport(item), sanitizedAuthRefs = sanitizeExport(authRefs);
  const sanitizedCatalog = sanitizeExport(rawCatalog), sanitizedSearch = sanitizeExport(completedSearch ?? null), sanitizedStudyArea = sanitizeExport(studyArea);
  const credentialsOmitted = authRefs.length > 0 || resolved.redacted_parameters.length > 0 || source?.redacted_parameters.length > 0 ||
    sourceBase?.redacted_parameters.length > 0 || original !== asset.href || JSON.stringify(sanitizedItem) !== JSON.stringify(item) ||
    JSON.stringify(sanitizedCatalog) !== JSON.stringify(rawCatalog) || JSON.stringify(sanitizedSearch) !== JSON.stringify(completedSearch ?? null) ||
    JSON.stringify(sanitizedStudyArea) !== JSON.stringify(studyArea) || JSON.stringify(sanitizedAuthRefs) !== JSON.stringify(authRefs);
  return {
    profile: SELECTION_PROFILE,
    created_at: new Date().toISOString(),
    discovery: {
      catalog: sanitizedCatalog,
      completed_search: sanitizedSearch,
      study_area_crs84: sanitizedStudyArea,
    },
    selection: {
      collection_id: typeof item.collection === 'string' ? item.collection : null,
      item_id: String(item.id),
      asset_key: assetKey,
      source_document: source ? {response_url: source.href, base_url: sourceBase.href,
        redacted_query_parameters: [...new Set([...source.redacted_parameters, ...sourceBase.redacted_parameters])].sort()} : null,
      original_href: original,
      resolved_http_href: resolved.href,
      redacted_query_parameters: resolved.redacted_parameters,
      declared: {
        media_type: typeof asset.type === 'string' ? asset.type : null,
        roles: Array.isArray(asset.roles) ? asset.roles.filter(value => typeof value === 'string') : [],
        auth_refs: sanitizedAuthRefs,
        crs: asset['proj:epsg'] ?? asset['proj:code'] ?? properties['proj:epsg'] ?? properties['proj:code'] ?? null,
      },
      access: {
        transient_credentials_omitted: credentialsOmitted,
        instruction: credentialsOmitted
          ? 'Obtain access through the provider, then use FieldWork\'s manual Raster input.'
          : 'Use FieldWork\'s manual Raster input; direct STAC import is not currently supported.',
      },
    },
    spatial: {
      item_footprint: sanitizeExport(item.geometry ?? null),
      geometry_is_null: item.geometry == null,
      spatial_window_readiness: item.geometry == null
        ? {verified: false, ready: false, reason: 'Item geometry is null; no footprint or spatial-window readiness is inferred.'}
        : {verified: false, ready: null, reason: 'Selection metadata does not verify raster coverage or a clipping window.'},
      study_area_crs84: sanitizeExport(studyArea),
      clipping_boundary: null,
      acquisition_boundary: null,
    },
    temporal: {
      item_datetime_utc: utc(properties.datetime),
      item_start_datetime_utc: utc(properties.start_datetime),
      item_end_datetime_utc: utc(properties.end_datetime),
      discovered_at_utc: utc(completedSearch?.retrieved_at),
    },
    evidence: {raw_stac_item: sanitizedItem, raw_stac_asset: sanitizedAsset},
    compatibility: {native_fieldwork_import: false, manual_raster_input: true},
  };
}

export function assessFieldworkRaster({width, height, bands, epsg, pixelIsArea, northUp, byteCount, geoKeys, modelTransformation, origin, resolution, bounds}) {
  const reasons = [];
  if (!Number.isSafeInteger(width) || width <= 0 || !Number.isSafeInteger(height) || height <= 0) reasons.push('requires positive safe-integer grid dimensions');
  if (bands !== 1) reasons.push(`requires one band (output has ${bands})`);
  if (epsg !== 4326) reasons.push(`requires EPSG:4326 (output is EPSG:${epsg})`);
  if (!pixelIsArea) reasons.push('requires PixelIsArea raster semantics');
  if (!northUp) reasons.push('requires a north-up grid');
  if (geoKeys?.model_type !== 2 || geoKeys?.geographic_type !== 4326 || geoKeys?.angular_units !== 9102) reasons.push('requires explicit geographic WGS84 GeoKeys');
  if (geoKeys?.raster_type !== 1) reasons.push('requires an explicit PixelIsArea GeoKey');
  if (modelTransformation !== false) reasons.push('requires no ModelTransformation tag');
  const validGrid = Array.isArray(origin) && origin.length === 2 && origin.every(Number.isFinite) && Array.isArray(resolution) && resolution.length === 2 &&
    resolution.every(Number.isFinite) && resolution[0] > 0 && resolution[1] < 0;
  if (!validGrid) reasons.push('requires a finite positive-X/negative-Y grid');
  const validBounds = Array.isArray(bounds) && bounds.length === 4 && bounds.every(Number.isFinite) &&
    bounds[0] >= -180 && bounds[2] <= 180 && bounds[1] >= -90 && bounds[3] <= 90 && bounds[0] < bounds[2] && bounds[1] < bounds[3];
  if (!validBounds) reasons.push('requires ordered bounds within CRS84 limits');
  if (validGrid && validBounds && Number.isSafeInteger(width) && width > 0 && Number.isSafeInteger(height) && height > 0) {
    const derived = [origin[0], origin[1] + height * resolution[1], origin[0] + width * resolution[0], origin[1]];
    const consistent = derived.every((value, index) => Math.abs(value - bounds[index]) <= 1e-9 * Math.max(1, Math.abs(value), Math.abs(bounds[index])));
    if (!consistent) reasons.push('requires bounds consistent with the raster origin, resolution and dimensions');
  }
  const cells = width * height;
  if (!Number.isSafeInteger(cells) || cells <= 0 || cells > FIELDWORK_RASTER_LIMITS.max_cells) reasons.push(`requires at most ${FIELDWORK_RASTER_LIMITS.max_cells.toLocaleString('en-US')} positive cells (output has ${Number.isFinite(cells) ? cells.toLocaleString('en-US') : cells})`);
  if (!Number.isSafeInteger(byteCount) || byteCount <= 0 || byteCount > FIELDWORK_RASTER_LIMITS.max_bytes) reasons.push(`requires 1 to ${FIELDWORK_RASTER_LIMITS.max_bytes.toLocaleString('en-US')} bytes (output has ${byteCount})`);
  return {compatible: reasons.length === 0, reasons, constraints: {...FIELDWORK_RASTER_LIMITS}, cells};
}

async function sha256(buffer) {
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
}

export async function buildFieldworkRasterHandoff({buffer, raster, sourceLineage, fieldworkProvenance, clippingBoundary, acquisitionBoundary}) {
  const bytes = buffer instanceof ArrayBuffer ? buffer : buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  const assessment = assessFieldworkRaster({...raster, byteCount: bytes.byteLength});
  if (!assessment.compatible) throw new Error(`Crop is not FieldWork-ready: ${assessment.reasons.join('; ')}.`);
  return {
    profile: RASTER_PROFILE,
    created_at: new Date().toISOString(),
    raster: {
      sha256: await sha256(bytes), byte_count: bytes.byteLength, crs: `EPSG:${raster.epsg}`,
      grid: {width: raster.width, height: raster.height, bands: raster.bands, pixel_is_area: raster.pixelIsArea, north_up: raster.northUp,
        geo_keys: raster.geoKeys ?? null, model_transformation_present: raster.modelTransformation ?? null,
        origin: raster.origin ?? null, resolution: raster.resolution ?? null},
      bounds: {clipping_boundary: sanitizeExport(clippingBoundary ?? null), acquisition_boundary: sanitizeExport(acquisitionBoundary ?? raster.bounds ?? null)},
    },
    provenance: sanitizeExport(sourceLineage),
    fieldwork: {manual_raster_input: true, native_import: false, satisfied_constraints: assessment.constraints,
      raster_provenance: sanitizeExport(fieldworkProvenance ?? {})},
  };
}
