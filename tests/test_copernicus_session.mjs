import test from 'node:test';
import assert from 'node:assert/strict';
import {CopernicusSession, protectedURL, readProtectedRange, downloadOriginal, originalFilename, SESSION_MS} from '../web/copernicus-session.js';
import {RangeSource} from '../web/raster-clip.js';
const url = 'https://download.dataspace.copernicus.eu/odata/v1/Products(ccf70f3b-7b04-41f9-ade5-1443a085748e)/Nodes(product)/Nodes(original.nc)/$value';
const secret = 'synthetic-test-token';
const jwt = exp => `e30.${btoa(JSON.stringify({exp}))}.synthetic`;
const auth = () => ({token: secret, expiresAt: Date.now() + 60000});
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };
function sessionJob() { const session = new CopernicusSession(); session.load(secret); return {session, job: session.job()}; }
function transport(response, inspect = () => {}) { return async (href, options) => {
  assert.equal(href, url); assert.equal(options.headers.Authorization, `Bearer ${secret}`);
  assert.equal(options.credentials, 'omit'); assert.equal(options.cache, 'no-store'); assert.equal(options.redirect, 'error');
  inspect(options); return response;
}; }
test('secret transport accepts only exact, unescaped genuine OData asset URLs before URL normalization', async () => {
  assert.equal(protectedURL(url), url);
  for (const ending of ['$value', '$zip']) assert(protectedURL(url.split('/Nodes(')[0] + '/' + ending));
  assert(protectedURL(url.replace('Nodes(product)', "Nodes('product')")));
  const invalid = [url + '?x=1', url + '#x', url.replace('https:', 'http:'), url.replace('.eu/', '.eu.evil.test/'), url.replace('.eu/', '.eu:443/'), url.replace('https://', 'https://user@'), url.replace('original.nc', '%2e%2e'), url.replace('original.nc', '..'), url.replace('original.nc', 'bad%20name.nc'), url.replace('/odata/', '/other/../odata/'), url.replace('/odata/', '/./odata/'), url.replace('/odata/', '/%6fdata/'), url.replace('/odata/', '/odata\\'), url.replace('ccf70f3b-7b04-41f9-ade5-1443a085748e', 'anything'), url.replace('/Nodes(product)', '/evil'), url.replace('$value', 'metadata'), url + '\n'];
  let calls = 0;
  for (const value of invalid) { assert.throws(() => protectedURL(value)); await assert.rejects(async () => readProtectedRange(value, auth(), {fetcher: () => { calls++; }})); }
  assert.equal(calls, 0);
});
test('session caps unverified expiry, clears old jobs on replace/invalid input/clear and never echoes input', () => {
  let now = Date.now(); const messages = [], session = new CopernicusSession(message => messages.push(message), () => now);
  try {
    session.load(secret); assert.equal(session.expiresAt, now + SESSION_MS);
    const first = session.job(); session.load('Bearer ' + secret); assert(first.signal.aborted); assert.throws(first.assert);
    const second = session.job(); session.load(jwt((now + 30000) / 1000)); assert(second.signal.aborted); assert.equal(session.expiresAt, now + 30000);
    const third = session.job(); now += 30001; assert.equal(session.loaded, false); assert(third.signal.aborted);
    for (const input of ['', 'x\ny', 'x\ty', 'x'.repeat(16385), jwt((now - 1) / 1000), 'a.%%.c', `e30.${btoa(JSON.stringify({typ: 'Refresh'}))}.synthetic`, `e30.${btoa(JSON.stringify({typ: 'Offline'}))}.synthetic`]) {
      session.load(secret); const job = session.job(); assert.throws(() => session.load(input), error => !error.message.includes(secret)); assert.equal(session.loaded, false); assert(job.signal.aborted);
    }
    assert(!messages.join(' ').includes(secret)); assert(!JSON.stringify(session).includes(secret));
  } finally { session.clear(); }
});
test('actual expiry timer aborts outstanding work', async () => {
  const session = new CopernicusSession(); session.load(jwt((Date.now() + 30) / 1000));
  const job = session.job(); await new Promise(resolve => job.signal.addEventListener('abort', resolve, {once: true})); assert.equal(session.loaded, false);
});
test('check exact 206 span and hidden headers, without full-file fallback', async () => {
  for (const headers of [{}, {'Content-Range': 'bytes 0-15/100', 'Content-Length': '16'}]) {
    const result = await readProtectedRange(url, auth(), {fetcher: transport(new Response(new Uint8Array(16), {status: 206, headers}), options => assert.equal(options.headers.Range, 'bytes=0-15'))});
    assert.equal(result.buffer.byteLength, 16);
  }
  let canceled = false, read = false;
  await assert.rejects(readProtectedRange(url, auth(), {fetcher: transport({status: 200, body: {cancel: async () => { canceled = true; }, getReader: () => { read = true; }}})}), /ignored HTTP Range/);
  assert(canceled); assert.equal(read, false);
  for (const [body, headers] of [[15, {}], [17, {}], [16, {'Content-Length': '15'}], [16, {'Content-Range': 'bytes 1-16/100'}], [16, {'Content-Range': 'bytes 0-15/15'}], [16, {'Content-Encoding': 'gzip'}], [16, {'Content-Range': 'bytes 0-14/100'}]]) {
    await assert.rejects(readProtectedRange(url, auth(), {fetcher: transport(new Response(new Uint8Array(body), {status: 206, headers}))}), /Incomplete|exceeded|Invalid/);
  }
  for (const status of [401, 403, 302, 500]) await assert.rejects(readProtectedRange(url, auth(), {fetcher: transport(new Response('', {status}))}), new RegExp(`${status}`));
  await assert.rejects(readProtectedRange(url, auth(), {fetcher: async () => { throw new TypeError('Failed to fetch'); }}), /network.*CORS.*redirects/);
  await assert.rejects(readProtectedRange(url, auth(), {fetcher: transport({status: 206, redirected: true})}), /Redirected/);
});
test('authenticated RangeSource checks source stability and expiry before each request', async () => {
  let calls = 0, current = auth();
  const source = new RangeSource(url, {auth: current, fetcher: (href, options) => { calls++; return transport(new Response(new Uint8Array(16), {status: 206, headers: {ETag: String(calls)}}))(href, options); }});
  await source.read({offset: 0, length: 16}); await assert.rejects(source.read({offset: 16, length: 16}), /Source changed/);
  current.expiresAt = Date.now() - 1; await assert.rejects(source.read({offset: 0, length: 16}), /expired/); assert.equal(calls, 2);
});
test('bounded original retains exact binary/NetCDF filename; reject declared and streamed overflow/truncation', async () => {
  assert.equal(originalFilename(url), 'original.nc'); assert.equal(originalFilename(url.replace('original.nc', 'source.tiff')), 'source.tiff');
  assert.equal(originalFilename(url.split('/Nodes(')[0] + '/$zip', {}, 'product'), 'product.zip');
  assert.equal(originalFilename(url.split('/Nodes(')[0] + '/Nodes(folder)/$zip'), 'folder.zip');
  assert.equal(originalFilename(url.split('/Nodes(')[0] + '/Nodes(folder.zip)/$zip'), 'folder.zip');
  const bytes = new Uint8Array([67, 68, 70, 1, 0, 255, 128, 10]);
  for (const headers of [{}, {'Content-Length': String(bytes.length)}]) {
    const {session, job} = sessionJob(); let saved;
    try { await downloadOriginal(url, job, {fetcher: transport(new Response(bytes, {headers})), save: (name, blob) => { saved = {name, blob}; }});
      assert.equal(saved.name, 'original.nc'); assert.deepEqual(new Uint8Array(await saved.blob.arrayBuffer()), bytes);
    } finally { job.finish(); session.clear(); }
  }
  for (const headers of [{}, {'Content-Length': '8'}, {'Content-Length': '9'}, {'Content-Length': 'bad'}]) {
    const {session, job} = sessionJob(); let saved = false;
    try { await assert.rejects(downloadOriginal(url, job, {limit: 7, fetcher: transport(new Response(bytes, {headers})), save: () => { saved = true; }})); assert.equal(saved, false); }
    finally { session.clear(); }
  }
  const {session, job} = sessionJob();
  try { await assert.rejects(downloadOriginal(url, job, {fetcher: transport(new Response(bytes, {headers: {'Content-Length': '9'}})), save: () => assert.fail()}), /Incomplete/); }
  finally { session.clear(); }
});
test('original encoding rejection is independent of the Blob size cap', async () => {
  const {session, job} = sessionJob(); let saved = false;
  try {
    await assert.rejects(downloadOriginal(url, job, {limit: 100, fetcher: transport(new Response(new Uint8Array(8), {headers: {'Content-Length': '8', 'Content-Encoding': 'gzip'}})), save: () => { saved = true; }}), /Encoded original response/);
    assert.equal(saved, false);
  } finally { session.clear(); }
});
test('raster ranges accept bounded EOF bodies while the explicit check stays strict', async () => {
  for (const headers of [{'Content-Range': 'bytes 8-15/16', 'Content-Length': '8'}, {'Content-Length': '8'}, {}]) {
    const source = new RangeSource(url, {auth: auth(), fetcher: transport(new Response(new Uint8Array(8), {status: 206, headers}))});
    assert.equal((await source.read({offset: 8, length: 16})).byteLength, 8);
    await assert.rejects(readProtectedRange(url, auth(), {offset: 8, length: 16, fetcher: transport(new Response(new Uint8Array(8), {status: 206, headers}))}), /Invalid|Incomplete/);
  }
  for (const [count, headers] of [[7, {'Content-Range': 'bytes 8-15/16'}], [9, {'Content-Range': 'bytes 8-15/16'}], [7, {'Content-Length': '8'}], [9, {'Content-Length': '8'}], [8, {'Content-Range': 'bytes 8-15/16', 'Content-Length': '9'}], [17, {}]]) {
    const source = new RangeSource(url, {auth: auth(), fetcher: transport(new Response(new Uint8Array(count), {status: 206, headers}))});
    await assert.rejects(source.read({offset: 8, length: 16}), /Invalid|Incomplete|exceeded/);
  }
});
test('clear and expiry after native WritableStream close begins preserve a truthful successful save', async () => {
  for (const action of ['clear', 'expiry']) {
    const gate = deferred(), closing = deferred(), expired = deferred(); let aborts = 0, committed = false;
    const session = new CopernicusSession(message => { if (message.startsWith('Session expired')) expired.resolve(); });
    session.load(action === 'expiry' ? jwt((Date.now() + 100) / 1000) : secret);
    const job = session.job();
    const writer = new WritableStream({write() {}, async close() { closing.resolve(); await gate.promise; committed = true; }, abort() { aborts++; }}).getWriter();
    const progress = [];
    const promise = downloadOriginal(url, job, {picker: async () => ({createWritable: async () => writer}), fetcher: async () => new Response('abc'), progress: value => progress.push(value)});
    await closing.promise;
    assert.equal(progress.at(-1).phase, 'commit');
    if (action === 'clear') session.clear(); else await expired.promise;
    assert.equal(session.loaded, false); assert.equal(aborts, 0);
    gate.resolve(); assert.equal(await promise, 3); assert(committed); assert.equal(aborts, 0);
    session.clear();
  }
});
test('valid-session idle timeouts settle stalled headers, body and native writer without saving', {timeout: 2000}, async () => {
  for (const stage of ['headers', 'body', 'writer']) {
    const {session, job} = sessionJob(), gate = deferred(); let abortRequested = false, closed = false, saved = false;
    const writer = new WritableStream({write: () => gate.promise, close: () => { closed = true; }}).getWriter();
    const writable = {write: value => writer.write(value), close: () => writer.close(), abort: () => { abortRequested = true; return writer.abort(); }};
    const fetcher = async () => stage === 'headers' ? gate.promise : stage === 'body' ? new Response(new ReadableStream({pull() { return gate.promise; }})) : new Response('abc');
    try {
      await assert.rejects(downloadOriginal(url, job, {requestMs: 15, picker: stage === 'writer' ? async () => ({createWritable: async () => writable}) : undefined, fetcher, save: () => { saved = true; }}), /timed out/);
      assert(session.loaded); assert.equal(saved, false); assert.equal(closed, false);
      if (stage === 'writer') assert(abortRequested);
    } finally { gate.resolve(); session.clear(); }
  }
});
test('streaming writer preserves bytes, has no Blob cap, and aborts on failure', async () => {
  for (const fail of [false, true]) {
    const {session, job} = sessionJob(); let closed = false, aborted = false; const writes = [];
    const writable = {write: async value => { writes.push(...value); if (fail) throw new Error('Write failed'); }, close: async () => { closed = true; }, abort: async () => { aborted = true; }};
    try {
      const promise = downloadOriginal(url, job, {picker: async options => { assert.equal(options.suggestedName, 'original.nc'); return {createWritable: async () => writable}; }, limit: 1, fetcher: transport(new Response(new Uint8Array([1, 2, 3]))), save: () => assert.fail()});
      if (fail) await assert.rejects(promise, /Write failed/); else { await promise; assert.deepEqual(writes, [1, 2, 3]); }
      assert.equal(closed, !fail); assert.equal(aborted, fail);
    } finally { session.clear(); }
  }
});
test('late picker, writable creation, fetch and write cannot commit after cancellation', async () => {
  for (const stage of ['picker', 'create', 'fetch', 'write']) {
    const {session, job} = sessionJob(), gate = deferred(), reached = deferred(); let closed = false, aborted = false, saves = 0, fetches = 0;
    const pause = async value => { reached.resolve(); await gate.promise; return value; };
    const writable = {write: async () => { if (stage === 'write') await pause(); }, close: async () => { closed = true; }, abort: async () => { aborted = true; }};
    const handle = {createWritable: () => stage === 'create' ? pause(writable) : Promise.resolve(writable)};
    const promise = downloadOriginal(url, job, {picker: stage === 'fetch' ? undefined : () => stage === 'picker' ? pause(handle) : Promise.resolve(handle), fetcher: async () => { fetches++; const response = new Response('abc'); return stage === 'fetch' ? pause(response) : response; }, save: () => { saves++; }});
    const rejected = assert.rejects(promise, /canceled|expired/);
    await reached.promise; session.clear(); gate.resolve(); await rejected;
    assert.equal(closed, false); assert.equal(saves, 0); if (['create', 'write'].includes(stage)) assert(aborted); if (stage === 'picker') assert.equal(fetches, 0);
  }
});
test('canceled/unsupported picker never silently starts a transfer', async () => {
  for (const name of ['AbortError', 'SecurityError']) {
    const {session, job} = sessionJob(); let fetched = false;
    try { await assert.rejects(downloadOriginal(url, job, {picker: async () => { throw new DOMException('hidden detail', name); }, fetcher: () => { fetched = true; }}), /canceled|picker unavailable/); assert.equal(fetched, false); }
    finally { session.clear(); }
  }
});
