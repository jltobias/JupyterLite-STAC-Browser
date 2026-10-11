/** Ephemeral CDSE access. Never attach this state to STAC metadata or exports. */
export const SESSION_MS = 10 * 60 * 1000;
export const ORIGINAL_LIMIT = 128 * 2 ** 20;
const ORIGIN = 'https://download.dataspace.copernicus.eu';
const UUID = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const assetPath = new RegExp(`^/odata/v1/Products\\(${UUID}\\)(?:/Nodes\\((?:[A-Za-z0-9_.-]+|'[A-Za-z0-9_.-]+')\\))*?/\\$(?:value|zip)$`);
export function protectedURL(value) {
  // Check the original string before URL normalization can erase traversal.
  if (typeof value !== 'string' || !value.startsWith(ORIGIN + '/') || /[%\\\s?#]/.test(value)) throw new Error('This asset is outside the permitted Copernicus download scope. Use the provider link.');
  const url = new URL(value);
  if (url.origin !== ORIGIN || url.username || url.password || !assetPath.test(value.slice(ORIGIN.length)) || /\/Nodes\('?\.{1,2}'?\)/.test(value)) throw new Error('This asset is outside the permitted Copernicus download scope. Use the provider link.');
  return url.href;
}
export function isProtectedURL(value) { try { protectedURL(value); return true; } catch { return false; } }
function tokenValue(input, now) {
  if (typeof input !== 'string' || /[\x00-\x1f\x7f]/.test(input) || input.length > 16384) throw new Error('Invalid access token. Paste only a short-lived CDSE OData access token.');
  const token = input.trim().replace(/^Bearer +/i, '');
  if (!token || !/^[A-Za-z0-9._~+\/=-]+$/.test(token)) throw new Error('Invalid access token. Paste only a short-lived CDSE OData access token.');
  let expiresAt = now + SESSION_MS;
  // Decoding is only a conservative lifetime cap; claims are NOT verified.
  if (token.split('.').length === 3) {
    try {
      const encoded = token.split('.')[1].replaceAll('-', '+').replaceAll('_', '/');
      const claims = JSON.parse(atob(encoded));
      if (!claims || typeof claims !== 'object' || Array.isArray(claims)) throw new Error();
      if (typeof claims.typ === 'string' && /refresh|offline/i.test(claims.typ)) throw new Error();
      if (Object.hasOwn(claims, 'exp')) {
        if (typeof claims.exp !== 'number' || !Number.isFinite(claims.exp)) throw new Error();
        expiresAt = Math.min(expiresAt, claims.exp * 1000);
      }
    } catch { throw new Error('Invalid token expiry information. Obtain a new CDSE OData access token.'); }
  }
  if (expiresAt <= now) throw new Error('This access token has expired. Obtain a new CDSE OData access token.');
  return {token, expiresAt};
}
export class CopernicusSession {
  #auth = null; #timer; #jobs = new Set(); #generation = 0;
  constructor(changed = () => {}, now = Date.now) { this.changed = changed; this.now = now; }
  get loaded() { if (this.#auth && this.now() >= this.#auth.expiresAt) this.clear('Session expired. Load a new access token.'); return Boolean(this.#auth); }
  get expiresAt() { return this.loaded ? this.#auth.expiresAt : null; }
  load(input) {
    this.clear('Previous session cleared.');
    this.#auth = tokenValue(input, this.now());
    this.#timer = setTimeout(() => this.clear('Session expired. Load a new access token.'), this.#auth.expiresAt - this.now());
    this.changed('Token loaded in page memory; access is not verified. Check an asset explicitly.');
  }
  cancelJobs() { for (const job of [...this.#jobs]) job.cancel(); }
  clear(message = 'Session cleared. No token is loaded.') {
    this.#auth = null; this.#generation++; clearTimeout(this.#timer); this.cancelJobs(); this.changed(message);
  }
  job() {
    if (!this.loaded) throw new Error('Load a CDSE OData access token first.');
    const generation = this.#generation, expiresAt = this.#auth.expiresAt, controller = new AbortController();
    // A picker may never resolve. Its job must not capture the old secret.
    const assert = () => { if (controller.signal.aborted || this.#generation !== generation || this.now() >= expiresAt) throw new Error('Operation canceled or session expired. No file was saved.'); };
    const job = {signal: controller.signal, assert, auth: () => { assert(); return {...this.#auth}; },
      cancel: () => { this.#jobs.delete(job); controller.abort(); }, finish: () => this.#jobs.delete(job)};
    this.#jobs.add(job); return job;
  }
}
function validAuth(auth) {
  if (!auth || typeof auth.token !== 'string' || !/^[A-Za-z0-9._~+\/=-]{1,16384}$/.test(auth.token) || !Number.isFinite(auth.expiresAt) || auth.expiresAt <= Date.now() || auth.expiresAt > Date.now() + SESSION_MS) throw new Error('Session expired or unavailable. Load a new access token.');
}
function statusError(status) {
  return new Error(status === 401 ? 'HTTP 401: this token was not accepted. Obtain a new CDSE OData access token.' : status === 403 ? 'HTTP 403: access to this asset is forbidden for this token.' : `Copernicus returned HTTP ${status}. Use the provider link or retry later.`);
}
function safeError(error, signal) {
  if (signal?.aborted || error.name === 'AbortError') return new Error('Operation canceled, timed out, or session expired. No file was saved.');
  if (error instanceof TypeError) return new Error('Browser could not reach this asset. Check network and provider CORS; redirects are blocked. Use the provider link.');
  return error;
}
// Fetch, streams and file sinks need not honor abort promptly themselves.
function untilAbort(promise, signal) {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException('Operation aborted', 'AbortError'));
    signal.addEventListener('abort', abort, {once: true});
    Promise.resolve(promise).then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}
function cleanup(action) { try { Promise.resolve(action()).catch(() => {}); } catch { /* Cleanup must not stall failure reporting. */ } }
/** Own the request until its body is finished, including expiry and idle timeout. */
async function transfer(url, auth, signal, fetcher, headers, consume, requestMs = 20000) {
  protectedURL(url); validAuth(auth); signal?.throwIfAborted();
  const controller = new AbortController(), abort = () => controller.abort();
  signal?.addEventListener('abort', abort, {once: true});
  const expiry = setTimeout(abort, auth.expiresAt - Date.now());
  let idle, response;
  const assert = () => { validAuth(auth); signal?.throwIfAborted(); controller.signal.throwIfAborted(); };
  const tick = () => { clearTimeout(idle); idle = setTimeout(abort, requestMs); assert(); };
  const wait = promise => untilAbort(promise, controller.signal);
  try {
    tick();
    response = await wait(fetcher(url, {headers: {...headers, Authorization: `Bearer ${auth.token}`}, credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer', signal: controller.signal}));
    assert();
    if (response.redirected || (response.url && response.url !== url)) throw new Error('Redirected asset refused. Use the provider link.');
    return await consume(response, {assert, tick, wait, signal: controller.signal});
  } catch (error) {
    controller.abort();
    cleanup(() => response?.body?.cancel());
    throw safeError(error, signal);
  } finally { clearTimeout(idle); clearTimeout(expiry); signal?.removeEventListener('abort', abort); }
}
export function readProtectedRange(url, auth, {offset = 0, length = 16, signal, fetcher = fetch, allowShort = false, requestMs} = {}) {
  if (![offset, length, offset + length].every(Number.isSafeInteger) || offset < 0 || length < 1 || length > 16 * 2 ** 20) throw new Error('Invalid bounded byte range.');
  return transfer(url, auth, signal, fetcher, {Range: `bytes=${offset}-${offset + length - 1}`}, async (response, guard) => {
    if (response.status !== 206) {
      cleanup(() => response.body?.cancel());
      if (response.status === 200) throw new Error('Provider ignored HTTP Range. Response canceled; full-file fallback is disabled. Original download remains available.');
      throw statusError(response.status);
    }
    const range = response.headers.get('Content-Range'), match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(range || '');
    const total = match ? Number(match[3]) : null;
    const expectedEnd = allowShort && total !== null ? Math.min(offset + length - 1, total - 1) : offset + length - 1;
    if ((range !== null && (!match || !Number.isSafeInteger(total) || total <= offset || (!allowShort && total <= expectedEnd) || Number(match[1]) !== offset || Number(match[2]) !== expectedEnd)) || (response.headers.get('Content-Encoding') || 'identity') !== 'identity') throw new Error('Invalid Content-Range or content encoding. No file was saved.');
    const advertised = response.headers.get('Content-Length');
    const expected = match ? expectedEnd - offset + 1 : allowShort && advertised !== null ? Number(advertised) : length;
    if (!Number.isSafeInteger(expected) || expected < 1 || expected > length || (advertised !== null && (!/^\d+$/.test(advertised) || Number(advertised) !== expected))) throw new Error('Invalid HTTP Range length. No file was saved.');
    const bytes = new Uint8Array(expected), reader = response.body?.getReader();
    if (!reader) throw new Error('Missing HTTP Range body.');
    let count = 0;
    try {
      while (true) {
        guard.tick(); const {done, value} = await guard.wait(reader.read()); guard.assert();
        if (done) break;
        if (count + value.byteLength > expected) throw new Error('Provider exceeded the requested byte range. Response canceled.');
        bytes.set(value, count); count += value.byteLength;
      }
      if (!count || (count !== expected && (!allowShort || match || advertised !== null))) throw new Error('Incomplete HTTP Range response; retry the provider.');
      return {buffer: count === expected ? bytes.buffer : bytes.buffer.slice(0, count), total, etag: response.headers.get('ETag')};
    } finally { cleanup(() => reader.cancel()); }
  }, requestMs);
}
export function originalFilename(url, asset = {}, key = 'asset') {
  protectedURL(url);
  const names = [...url.matchAll(/\/Nodes\('?([^')]+)'?\)/g)];
  let name = names.at(-1)?.[1];
  if (!name) name = `${key}.zip`; // OData product values are archives.
  if (url.endsWith('/$zip') && !/\.zip$/i.test(name)) name += '.zip';
  return name.replace(/[^A-Za-z0-9_.-]/g, '_').slice(-180) || 'asset';
}
/** Picker must be invoked by the click handler before its first await. */
export async function downloadOriginal(url, job, {picker, filename = originalFilename(url), save, progress = () => {}, fetcher = fetch, limit = ORIGINAL_LIMIT, requestMs} = {}) {
  protectedURL(url); job.assert();
  let writable, completed = false, committing = false;
  const abortWrite = () => { if (writable && !completed && !committing) cleanup(() => writable.abort()); };
  job.signal.addEventListener('abort', abortWrite, {once: true});
  try {
    if (picker) {
      let handle;
      try { handle = await picker({suggestedName: filename}); }
      catch (error) { if (error.name === 'AbortError') throw new Error('Save canceled. No file was saved.'); throw new Error('File picker unavailable here. Use the bounded browser download button or the provider link.'); }
      job.assert(); writable = await handle.createWritable(); job.assert();
    }
    const result = await transfer(url, job.auth(), job.signal, fetcher, {}, async (response, guard) => {
      if (response.status !== 200) throw statusError(response.status);
      const advertised = response.headers.get('Content-Length');
      const total = advertised === null ? null : Number(advertised);
      if (advertised !== null && (!/^\d+$/.test(advertised) || !Number.isSafeInteger(total) || total < 0)) throw new Error('Invalid original file length.');
      if (!writable && total > limit) throw new Error('Original exceeds the 128 MiB browser download limit. Use Save original to file or the provider link.');
      if ((response.headers.get('Content-Encoding') || 'identity') !== 'identity') throw new Error('Encoded original response refused to preserve file bytes.');
      const reader = response.body?.getReader(), chunks = [];
      if (!reader) throw new Error('Missing original file body.');
      let bytes = 0;
      try {
        while (true) {
          guard.tick(); job.assert(); const {done, value} = await guard.wait(reader.read()); guard.assert(); job.assert();
          if (done) break;
          bytes += value.byteLength;
          if (!Number.isSafeInteger(bytes) || (!writable && bytes > limit) || (total !== null && bytes > total)) throw new Error('Original exceeds the expected size or the 128 MiB browser download limit.');
          if (writable) { guard.tick(); await guard.wait(writable.write(value)); guard.assert(); job.assert(); }
          else chunks.push(value);
          progress({bytes, total});
        }
        if (!bytes || (total !== null && bytes !== total)) throw new Error('Incomplete original download. No file was saved.');
        return {bytes, blob: writable ? null : new Blob(chunks, {type: 'application/octet-stream'})};
      } finally { cleanup(() => reader.cancel()); }
    }, requestMs);
    job.assert();
    if (writable) {
      // Closing commits the completed file. It cannot be undone by later cancellation.
      committing = true; job.finish(); job.signal.removeEventListener('abort', abortWrite);
      progress({phase: 'commit', bytes: result.bytes});
      await writable.close();
    }
    else { job.assert(); save(filename, result.blob); }
    completed = true; return result.bytes;
  } catch (error) {
    if (committing) throw new Error('File could not finish saving. Check the selected file before retrying.');
    abortWrite(); throw safeError(error, job.signal);
  }
  finally { job.signal.removeEventListener('abort', abortWrite); }
}
