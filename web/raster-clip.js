import {bboxValue, safeURL} from './stac.js';
import {protectedURL, readProtectedRange} from './copernicus-session.js';

export const CLIP_LIMITS = Object.freeze({output: 64 * 2 ** 20, transfer: 128 * 2 ** 20,
  decoded: 128 * 2 ** 20, block: 16 * 2 ** 20, metadata: 8 * 2 ** 20, requests: 4096,
  requestMs: 20000, jobMs: 120000});
const limitError = () => new Error('Crop exceeds browser resource limits. Choose a smaller study area or use a provider subset service.');
const checkSize = (value, limit) => { if (!Number.isSafeInteger(value) || value < 0 || value > limit) throw limitError(); return value; };

/** Only exact, single HTTP byte ranges are accepted. Never consume a 200 body. */
export class RangeSource {
  constructor(url, {signal, progress = () => {}, fetcher = fetch, limits = CLIP_LIMITS, auth} = {}) {
    this.url = auth ? protectedURL(url) : safeURL(url); this.auth = auth; this.signal = signal; this.progress = progress;
    this.fetcher = fetcher; this.limits = limits; this.bytes = 0; this.requests = 0;
    this.fileSize = null; this.etag = null; this.tail = Promise.resolve();
  }
  fetch(slices) {
    // Serial scheduling also bounds metadata requests initiated by the reader.
    return Promise.all(slices.map(slice => {
      const task = this.tail.then(() => this.read(slice));
      this.tail = task.catch(() => {}); return task;
    }));
  }
  async read({offset, length}) {
    this.signal?.throwIfAborted();
    checkSize(offset, Number.MAX_SAFE_INTEGER); checkSize(length, this.limits.block);
    if (!length) return new ArrayBuffer(0);
    if (++this.requests > this.limits.requests) throw limitError();
    if (this.fileSize !== null) length = Math.min(length, this.fileSize - offset);
    if (length <= 0) throw new Error('Invalid raster byte offset.');
    checkSize(this.bytes + length, this.limits.transfer);
    if (this.auth) {
      const result = await readProtectedRange(this.url, this.auth, {offset, length, signal: this.signal, fetcher: this.fetcher, allowShort: true, requestMs: this.limits.requestMs});
      if ((this.fileSize !== null && result.total !== null && result.total !== this.fileSize) || (this.etag && result.etag !== this.etag)) throw new Error('Source changed during clipping. Retry the selected asset.');
      this.fileSize ??= result.total; this.etag ||= result.etag;
      this.bytes += result.buffer.byteLength; this.progress({phase: 'transfer', bytes: this.bytes, requests: this.requests});
      return result.buffer;
    }
    const controller = new AbortController();
    const abort = () => controller.abort();
    this.signal?.addEventListener('abort', abort, {once: true});
    const timer = setTimeout(abort, this.limits.requestMs);
    let response;
    try {
      const fetcher = this.fetcher;
      response = await fetcher(this.url, {headers: {Range: `bytes=${offset}-${offset + length - 1}`},
        credentials: 'omit', signal: controller.signal});
      if (response.status !== 206) {
        await response.body?.cancel();
        throw new Error(response.status === 200
          ? 'Provider ignored HTTP Range. Response canceled; full-file fallback is disabled. Use the full-file link or a provider subset service.'
          : `Provider returned HTTP ${response.status}. Clipping requires public, CORS-accessible HTTP Range responses; use provider access instructions.`);
      }
      const rangeHeader = response.headers.get('Content-Range');
      const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(rangeHeader || '');
      const start = Number(match?.[1]), end = Number(match?.[2]), total = Number(match?.[3]);
      if ((rangeHeader && (!match || !Number.isSafeInteger(total) || total < 1 || start !== offset || end !== Math.min(offset + length - 1, total - 1) ||
          (this.fileSize !== null && total !== this.fileSize))) || (response.headers.get('Content-Encoding') || 'identity') !== 'identity') {
        await response.body?.cancel(); throw new Error('Provider returned an invalid Content-Range or content encoding. No full-file fallback is permitted.');
      }
      const etag = response.headers.get('ETag');
      if (this.etag && etag !== this.etag) { await response.body?.cancel(); throw new Error('Source changed during clipping. Retry the selected asset.'); }
      this.etag ||= etag; if (match) this.fileSize = total;
      // CORS need not expose Content-Range. A 206 is still mandatory; cap the
      // streamed body at the requested length and check any exposed length.
      const advertised = response.headers.get('Content-Length');
      const count = match ? end - start + 1 : advertised !== null ? Number(advertised) : length;
      if (!Number.isSafeInteger(count) || count < 1 || count > length) { await response.body?.cancel(); throw new Error('Provider exceeded the requested byte range. Response canceled.'); }
      const output = new Uint8Array(count), reader = response.body.getReader();
      let position = 0;
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        if (position + value.byteLength > count) { await reader.cancel(); throw new Error('Provider exceeded the requested byte range. Response canceled.'); }
        output.set(value, position); position += value.byteLength;
      }
      if (!position || ((match || advertised !== null) && position !== count)) throw new Error('Incomplete HTTP Range response; retry the provider.');
      this.bytes += position; this.progress({phase: 'transfer', bytes: this.bytes, requests: this.requests});
      return position === count ? output.buffer : output.buffer.slice(0, position);
    } catch (error) {
      controller.abort();
      this.signal?.throwIfAborted();
      if (error.name === 'AbortError') throw new Error('Raster request timed out after 20 seconds. Try a smaller area or retry the provider.');
      if (error instanceof TypeError) throw new Error('Raster is unavailable to this browser. Check provider CORS, HTTPS and authentication. No full-file fallback was attempted.');
      throw error;
    } finally { clearTimeout(timer); this.signal?.removeEventListener('abort', abort); }
  }
}

// Validate IFD counts before GeoTIFF.js creates deferred arrays from untrusted sizes.
async function preflight(source, limits) {
  const header = new DataView((await source.fetch([{offset: 0, length: 16}]))[0]);
  const endian = header.getUint16(0), little = endian === 0x4949;
  if (![0x4949, 0x4d4d].includes(endian)) throw new Error('Asset is not a TIFF raster.');
  // GeoTIFF.js 3.0.5 lazy array access assumes little-endian. Fail conservatively.
  if (!little) throw new Error('Big-endian TIFF encoding is not supported by this crop reader. Use a provider subset service.');
  const magic = header.getUint16(2, little), big = magic === 43;
  if (![42, 43].includes(magic) || (big && (header.getUint16(4, true) !== 8 || header.getUint16(6, true) !== 0))) throw new Error('Unsupported TIFF header.');
  const number64 = (view, at) => checkSize(Number(view.getBigUint64(at, little)), Number.MAX_SAFE_INTEGER);
  let offset = big ? number64(header, 8) : header.getUint32(4, little);
  const sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8, 17: 8, 18: 8};
  let allocation = 0; const visited = new Set();
  // Masks can follow the full-resolution IFD and ordinary COG overviews. Scan
  // the complete bounded chain before reading pixels; never discard validity.
  while (offset) {
    if (visited.has(offset)) throw new Error('Invalid cyclic TIFF image directory.');
    if (visited.size >= 64) throw limitError();
    visited.add(offset);
    const prefix = new DataView((await source.fetch([{offset, length: big ? 8 : 2}]))[0]);
    const count = big ? number64(prefix, 0) : prefix.getUint16(0, little);
    checkSize(count, 4096);
    const entryBytes = count * (big ? 20 : 12);
    const entries = new DataView((await source.fetch([{offset: offset + (big ? 8 : 2), length: entryBytes + (big ? 8 : 4)}]))[0]);
    for (let i = 0; i < count; i++) {
      const at = i * (big ? 20 : 12), tag = entries.getUint16(at, little), type = entries.getUint16(at + 2, little);
      const values = big ? number64(entries, at + 4) : entries.getUint32(at + 4, little);
      if (!sizes[type]) throw new Error('Unsupported TIFF metadata encoding.');
      allocation += values * Math.max(8, sizes[type]);
      checkSize(allocation, limits.metadata);
      if (tag === 330 && values) throw new Error('TIFF SubIFDs are unsupported: nested validity masks cannot be safely preserved. Use a provider subset service.');
      if ([254, 262, 266].includes(tag)) {
        if (values !== 1 || ![3, 4].includes(type)) throw new Error('Unsupported TIFF image directory encoding.');
        const valueAt = at + (big ? 12 : 8), value = type === 3 ? entries.getUint16(valueAt, little) : entries.getUint32(valueAt, little);
        if ((tag === 254 && (value & 4)) || (tag === 262 && value === 4)) throw new Error('Internal TIFF validity masks are unsupported; clipping would discard invalid-pixel information. Use a provider subset service.');
        if (tag === 266 && value !== 1) throw new Error('Unsupported TIFF FillOrder. Only FillOrder=1 is supported.');
      }
    }
    offset = big ? number64(entries, entryBytes) : entries.getUint32(entryBytes, little);
  }
}

export function cropWindow(bbox, grid, project) {
  bbox = bboxValue(bbox);
  const {epsg, x, y, dx, dy, width, height, point = false} = grid;
  if (![width, height].every(n => Number.isSafeInteger(n) && n > 0)) throw new Error('Invalid raster dimensions.');
  if (![x, y, dx, dy].every(Number.isFinite) || dx <= 0 || dy >= 0) throw new Error('Only north-up raster grids are supported.');
  if (![4326, 3857].includes(epsg) && !(epsg >= 32601 && epsg <= 32660) && !(epsg >= 32701 && epsg <= 32760)) throw new Error('Unsupported CRS. Use WGS84, Web Mercator or WGS84 UTM source grids.');
  if (epsg === 3857 && (bbox[1] < -85.05112878 || bbox[3] > 85.05112878)) throw new Error('Web Mercator crops must stay within ±85.05112878° latitude.');
  if (epsg >= 32601) {
    const zone = epsg % 100, center = zone * 6 - 183;
    if (bbox[1] < -80 || bbox[3] > 84 || bbox[0] < center - 9 || bbox[2] > center + 9) throw new Error('Study area is outside this UTM grid’s supported zone neighborhood (±9°). Choose a smaller area.');
  }
  const originX = x - (point ? dx / 2 : 0), originY = y - (point ? dy / 2 : 0);
  const points = [];
  // Densify curved UTM edges; include the equator and central meridian, their extrema.
  const longs = [bbox[0], bbox[2]], lats = [bbox[1], bbox[3]];
  if (epsg >= 32601) { const central = (epsg % 100) * 6 - 183; if (central > bbox[0] && central < bbox[2]) longs.push(central); if (bbox[1] < 0 && bbox[3] > 0) lats.push(0); }
  for (let i = 0; i <= 256; i++) {
    const lon = bbox[0] + (bbox[2] - bbox[0]) * i / 256, lat = bbox[1] + (bbox[3] - bbox[1]) * i / 256;
    for (const a of longs) points.push(project([a, lat]));
    for (const b of lats) points.push(project([lon, b]));
  }
  if (!points.flat().every(Number.isFinite)) throw new Error('Study area cannot be projected into the source CRS.');
  const bounds = [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1])), Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))];
  const sourceBounds = [originX, originY + height * dy, originX + width * dx, originY];
  if (bounds[0] >= sourceBounds[2] || bounds[2] <= sourceBounds[0] || bounds[1] >= sourceBounds[3] || bounds[3] <= sourceBounds[1]) throw new Error('Study bounding box does not overlap this raster.');
  const snap = value => Math.abs(value - Math.round(value)) < 1e-7 ? Math.round(value) : value;
  const window = [Math.max(0, Math.floor(snap((bounds[0] - originX) / dx))), Math.max(0, Math.floor(snap((bounds[3] - originY) / dy))),
    Math.min(width, Math.ceil(snap((bounds[2] - originX) / dx))), Math.min(height, Math.ceil(snap((bounds[1] - originY) / dy)))];
  if (window[0] >= window[2] || window[1] >= window[3]) throw new Error('Study bounding box has no intersecting pixels.');
  return {window, bounds: [originX + window[0] * dx, originY + window[3] * dy, originX + window[2] * dx, originY + window[1] * dy]};
}

/** Dynamic TIFF directory layout: metadata is sized before any offsets are written. */
export function writeGeoTIFF(pixels, {width, height, samples, bits, format, tags = []}, limit = CLIP_LIMITS.output) {
  const entries = new Map(tags.map(([id, type, values]) => [id, {id, type, values}]));
  const set = (id, type, values) => entries.set(id, {id, type, values});
  for (const [id, type, values] of [[256, 4, [width]], [257, 4, [height]], [258, 3, Array(samples).fill(bits)], [259, 3, [1]],
    [273, 4, [0]], [277, 3, [samples]], [278, 4, [height]], [279, 4, [pixels.byteLength]], [284, 3, [1]], [339, 3, Array(samples).fill(format)]]) set(id, type, values);
  const sorted = [...entries.values()].sort((a, b) => a.id - b.id), sizes = {2: 1, 3: 2, 4: 4, 12: 8};
  let end = 8 + 2 + sorted.length * 12 + 4;
  for (const tag of sorted) {
    if (tag.type === 2) tag.values = new TextEncoder().encode(String(tag.values).replace(/\0+$/, '') + '\0');
    tag.length = tag.values.length * sizes[tag.type];
    if (!Number.isSafeInteger(tag.length)) throw new Error('Unsupported output metadata type.');
    if (tag.length > 4) { end = Math.ceil(end / 8) * 8; tag.offset = end; end += tag.length; }
  }
  const dataOffset = Math.ceil(end / 8) * 8, buffer = new ArrayBuffer(checkSize(dataOffset + pixels.byteLength, limit)), view = new DataView(buffer);
  entries.get(273).values[0] = dataOffset;
  view.setUint16(0, 0x4949, true); view.setUint16(2, 42, true); view.setUint32(4, 8, true); view.setUint16(8, sorted.length, true);
  sorted.forEach((tag, i) => {
    const at = 10 + i * 12; view.setUint16(at, tag.id, true); view.setUint16(at + 2, tag.type, true); view.setUint32(at + 4, tag.values.length, true);
    if (tag.offset) view.setUint32(at + 8, tag.offset, true);
    const base = tag.offset || at + 8;
    for (let j = 0; j < tag.values.length; j++) {
      const offset = base + j * sizes[tag.type], value = tag.values[j];
      if (tag.type === 2) view.setUint8(offset, value);
      else if (tag.type === 3) view.setUint16(offset, value, true);
      else if (tag.type === 4) view.setUint32(offset, value, true);
      else view.setFloat64(offset, value, true);
    }
  });
  // Typed arrays are native-endian; emit numeric values explicitly for portability.
  const setter = format === 3 ? (bits === 32 ? 'setFloat32' : 'setFloat64') : `${format === 2 ? 'setInt' : 'setUint'}${bits}`;
  for (let i = 0; i < pixels.length; i++) view[setter](dataOffset + i * bits / 8, pixels[i], true);
  return buffer;
}

// TIFF LZW, with fixed-size output and dictionary instead of unbounded JS arrays.
function boundedLZW(buffer, size) {
  const input = new Uint8Array(buffer), output = new Uint8Array(size), prefix = new Uint16Array(4096), suffix = new Uint8Array(4096), stack = new Uint8Array(4096);
  let bit = 0, width = 9, next = 258, old = -1, first = 0, position = 0;
  const emit = value => { if (position >= size) throw limitError(); output[position++] = value; };
  while (bit + width <= input.length * 8) {
    let code = 0;
    for (let i = 0; i < width; i++, bit++) code = code * 2 + ((input[bit >> 3] >> (7 - bit % 8)) & 1);
    if (code === 257) return output.buffer.slice(0, position);
    if (code === 256) { width = 9; next = 258; old = -1; continue; }
    const current = code; let top = 0;
    if (code === next && old >= 0) { stack[top++] = first; code = old; }
    else if (code >= next) throw new Error('Invalid LZW raster block.');
    while (code >= 258) { if (top >= 4095) throw new Error('Invalid LZW dictionary.'); stack[top++] = suffix[code]; code = prefix[code]; }
    if (code > 255) throw new Error('Invalid LZW raster code.');
    first = code; stack[top++] = first;
    while (top) emit(stack[--top]);
    if (old >= 0 && next < 4096) { prefix[next] = old; suffix[next++] = first; if (next === (1 << width) - 1 && width < 12) width++; }
    old = current;
  }
  throw new Error('Incomplete LZW raster block.');
}

export async function clipRaster(request, {GeoTIFF, proj4, fetcher = fetch, signal, progress = () => {}, limits = CLIP_LIMITS}) {
  const bbox = bboxValue(request.bbox), source = new RangeSource(request.url, {fetcher, signal, progress, limits, auth: request.auth});
  await preflight(source, limits);
  const tiff = await GeoTIFF.GeoTIFF.fromSource(source, {cache: false}), image = await tiff.getImage(0), fd = image.getFileDirectory();
  const keys = await image.getGeoKeys(), epsg = Number(keys?.ProjectedCSTypeGeoKey || keys?.GeographicTypeGeoKey);
  if ((keys?.GTModelTypeGeoKey === 1 && keys?.ProjLinearUnitsGeoKey && keys.ProjLinearUnitsGeoKey !== 9001) ||
    (keys?.GeogAngularUnitsGeoKey && keys.GeogAngularUnitsGeoKey !== 9102)) throw new Error('Unsupported CRS units.');
  const transform = await fd.loadValue('ModelTransformation'), scale = await fd.loadValue('ModelPixelScale'), tie = await fd.loadValue('ModelTiepoint');
  let x, y, dx, dy;
  if (transform) {
    if (transform.length !== 16 || [1, 2, 4, 6, 8, 9, 12, 13, 14].some(i => transform[i] !== 0) || transform[15] !== 1) throw new Error('Rotated or sheared raster grids are not supported.');
    [x, y, dx, dy] = [transform[3], transform[7], transform[0], transform[5]];
  } else {
    if (!scale || tie?.length !== 6) throw new Error('Raster lacks a supported north-up affine transform.');
    dx = scale[0]; dy = -scale[1]; x = tie[3] - tie[0] * dx; y = tie[4] - tie[1] * dy;
  }
  if ((epsg >= 32601 && epsg <= 32660) || (epsg >= 32701 && epsg <= 32760)) proj4.defs(`EPSG:${epsg}`, `+proj=utm +zone=${epsg % 100} ${epsg >= 32701 ? '+south' : ''} +datum=WGS84 +units=m +no_defs`);
  const project = p => epsg === 4326 ? p : proj4('EPSG:4326', `EPSG:${epsg}`, p);
  const grid = {epsg, x, y, dx, dy, width: image.getWidth(), height: image.getHeight(), point: keys?.GTRasterTypeGeoKey === 2};
  const {window, bounds} = cropWindow(bbox, grid, project), [left, top, right, bottom] = window;
  const width = right - left, height = bottom - top, samples = image.getSamplesPerPixel(), bits = image.getBitsPerSample(), format = image.getSampleFormat();
  if (!Number.isInteger(samples) || samples < 1 || samples > 32 || !([1, 2].includes(format) ? [8, 16, 32] : format === 3 ? [32, 64] : []).includes(bits) ||
    Array.from({length: samples}, (_, s) => image.getBitsPerSample(s) !== bits || image.getSampleFormat(s) !== format).some(Boolean)) throw new Error('Unsupported sample encoding or heterogeneous bands. Use homogeneous 8/16/32-bit integer or 32/64-bit floating-point bands.');
  const photo = fd.getValue('PhotometricInterpretation') ?? 1, compression = fd.getValue('Compression') || 1, predictor = fd.getValue('Predictor') || 1;
  if (![0, 1, 2, 3].includes(photo) || ![1, 5, 8, 32946].includes(compression) || ![1, 2, 3].includes(predictor) || (predictor === 2 && bits === 64) || (predictor === 3 && format !== 3) || ![1, 2].includes(image.planarConfiguration) || (fd.getValue('Orientation') || 1) !== 1 || (fd.getValue('NewSubfileType') || 0) !== 0) throw new Error('Unsupported raster encoding, orientation or overview. Supported compression: uncompressed, LZW and Deflate.');
  const pixelBytes = samples * bits / 8, outputBytes = checkSize(width * height * pixelBytes, limits.output);
  const tileWidth = image.getTileWidth(), tileHeight = image.getTileHeight();
  checkSize(tileWidth * tileHeight * pixelBytes, limits.block);
  const blocks = (Math.ceil(right / tileWidth) - Math.floor(left / tileWidth)) * (Math.ceil(bottom / tileHeight) - Math.floor(top / tileHeight));
  checkSize(blocks * tileWidth * tileHeight * pixelBytes, limits.decoded);
  const provenance = {...request.provenance, source_url: request.provenance?.source_url || request.url, requested_bbox: bbox, pixel_window: window, output_bounds: bounds,
    output_crs: `EPSG:${epsg}`, width, height, bands: samples, bits_per_sample: bits, sample_format: format,
    created_at: new Date().toISOString(), method: 'Source-resolution intersecting pixel window; no resampling. Polygon envelope if applicable.', reader: 'GeoTIFF.js 3.0.5'};
  progress({phase: 'estimate', width, height, bounds, epsg, outputBytes, blocks});
  const tags = [[262, 3, [photo]], [33550, 12, [dx, -dy, scale?.[2] || 0]], [33922, 12, [0, 0, 0, x + left * dx, y + top * dy, tie?.[5] || 0]]];
  for (const [id, type, name] of [[34735, 3, 'GeoKeyDirectory'], [34736, 12, 'GeoDoubleParams'], [34737, 2, 'GeoAsciiParams'], [42113, 2, 'GDAL_NODATA'], [42112, 2, 'GDAL_METADATA'], [270, 2, 'ImageDescription'], [320, 3, 'ColorMap'], [338, 3, 'ExtraSamples']]) {
    const value = await fd.loadValue(name); if (value !== undefined) tags.push([id, type, value]);
  }
  const Typed = format === 3 ? (bits === 32 ? Float32Array : Float64Array) : (format === 2 ? {8: Int8Array, 16: Int16Array, 32: Int32Array} : {8: Uint8Array, 16: Uint16Array, 32: Uint32Array})[bits];
  const pixels = new Typed(outputBytes / (bits / 8));
  let completed = 0;
  for (let by = Math.floor(top / tileHeight); by < Math.ceil(bottom / tileHeight); by++) {
    for (let bx = Math.floor(left / tileWidth); bx < Math.ceil(right / tileWidth); bx++) {
      signal?.throwIfAborted();
      const part = [Math.max(left, bx * tileWidth), Math.max(top, by * tileHeight), Math.min(right, (bx + 1) * tileWidth), Math.min(bottom, (by + 1) * tileHeight)];
      const blockBytes = tileWidth * image.getBlockHeight(by) * (image.planarConfiguration === 2 ? bits / 8 : pixelBytes);
      class Decoder extends GeoTIFF.BaseDecoder {
        async decodeBlock(buffer) {
          if (compression === 5) return boundedLZW(buffer, blockBytes);
          if (compression === 1) { if (buffer.byteLength > blockBytes) throw limitError(); return buffer; }
          const reader = new Blob([buffer]).stream().pipeThrough(new DecompressionStream('deflate')).getReader();
          const decoded = new Uint8Array(blockBytes); let offset = 0;
          while (true) {
            const {done, value} = await reader.read(); if (done) break;
            if (offset + value.length > blockBytes) { await reader.cancel(); throw limitError(); }
            decoded.set(value, offset); offset += value.length;
          }
          return decoded.buffer.slice(0, offset);
        }
      }
      const pool = {bindParameters: (_, params) => new Decoder(params)};
      // One intersecting tile at a time, with all source bands, at native resolution.
      const values = await image.readRasters({window: part, interleave: true, pool, signal});
      // GeoTIFF.js fills sparse blocks with `nodata || 0`, which loses NaN.
      // Preserve the declared NoData for sparse source blocks explicitly.
      const across = Math.ceil(grid.width / tileWidth), down = Math.ceil(grid.height / tileHeight);
      const noData = image.getGDALNoData();
      for (let sample = 0; sample < samples; sample++) {
        const index = by * across + bx + (image.planarConfiguration === 2 ? sample * across * down : 0);
        const count = Number(await fd.loadValueIndexed(image.isTiled ? 'TileByteCounts' : 'StripByteCounts', index));
        if (count === 0) for (let i = sample; i < values.length; i += samples) values[i] = noData ?? 0;
      }
      const rowLength = (part[2] - part[0]) * samples;
      for (let row = part[1]; row < part[3]; row++) pixels.set(values.subarray((row - part[1]) * rowLength, (row - part[1] + 1) * rowLength), ((row - top) * width + part[0] - left) * samples);
      progress({phase: 'pixels', completed: ++completed, blocks, bytes: source.bytes});
    }
  }
  signal?.throwIfAborted();
  progress({phase: 'write'});
  Object.assign(provenance, {transferred_bytes: source.bytes, range_requests: source.requests});
  const escaped = JSON.stringify(provenance).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  const gdal = tags.find(t => t[0] === 42112), entry = `<Item name="STAC_BROWSER_PROVENANCE">${escaped}</Item>`;
  if (gdal) {
    if (!String(gdal[2]).includes('</GDALMetadata>')) throw new Error('Unsupported GDAL band metadata; cannot preserve it safely.');
    // Cached whole-source distributions no longer describe the output window.
    // Keep descriptions, units, scales, offsets and other nonspatial metadata.
    gdal[2] = String(gdal[2]).replace(/<Item\b([^>]*)>[\s\S]*?<\/Item\s*>/gi, (item, attributes) => {
      const name = /\bname\s*=\s*(["'])(.*?)\1/i.exec(attributes)?.[2] || '';
      return /^(?:STATISTICS(?:_|$)|HISTOGRAM(?:_|$)|HISTO(?:MIN|MAX|NUMBUCKETS|BINVALUES)$|STAC_BROWSER_PROVENANCE$)/i.test(name) ? '' : item;
    }).replace('</GDALMetadata>', entry + '</GDALMetadata>');
  } else tags.push([42112, 2, `<GDALMetadata>${entry}</GDALMetadata>`]);
  const buffer = writeGeoTIFF(pixels, {width, height, samples, bits, format, tags}, limits.output);
  return {buffer, provenance, width, height, bounds, epsg, bands: samples, pixelIsArea: !grid.point, northUp: true,
    geoKeys: {model_type: Number(keys?.GTModelTypeGeoKey), raster_type: Number(keys?.GTRasterTypeGeoKey),
      geographic_type: Number(keys?.GeographicTypeGeoKey), angular_units: Number(keys?.GeogAngularUnitsGeoKey)},
    modelTransformation: false, origin: [x + left * dx, y + top * dy], resolution: [dx, dy]};
}

/** A fresh worker per explicit job bounds lifetime and makes Cancel immediate. */
export function startRasterClip(request, progress) {
  const worker = new Worker(new URL('./raster-clip-worker.js', import.meta.url));
  let rejectJob, settled = false;
  const close = () => { settled = true; clearTimeout(timer); worker.terminate(); };
  const promise = new Promise((resolve, reject) => {
    rejectJob = reject;
    worker.onmessage = ({data}) => {
      if (settled) return;
      if (data.type === 'progress') progress?.(data.value);
      else { close(); if (data.type === 'result') resolve(data.value); else reject(new Error(data.message)); }
    };
    worker.onerror = event => { event.preventDefault(); close(); reject(new Error('Raster worker could not process this asset. Check its encoding and browser support.')); };
  });
  const cancel = (message = 'Crop canceled. No file was saved.') => { if (!settled) { close(); rejectJob(new Error(message)); } };
  const timer = setTimeout(() => cancel('Crop exceeded two minutes. Choose a smaller study area or use the provider subset service.'), CLIP_LIMITS.jobMs);
  worker.postMessage(structuredClone(request));
  return {promise, cancel};
}
