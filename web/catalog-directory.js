/** STAC Index discovery only: no provider requests until the main Connect action. */
import {safeURL, fetchJSON} from './stac.js';

export const DIRECTORY_SOURCE = 'https://stacindex.org/catalogs?access=public';
export const DIRECTORY_API = 'https://stacindex.org/api/catalogs';
const fields = ['id', 'slug', 'title', 'url', 'access', 'isApi'];
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const alphabetical = value => value.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;

export function normalizeCatalogs(data) {
  if (!Array.isArray(data) || !data.length || data.length > 5000) throw new Error('Directory must be a nonempty array of at most 5000 listings.');
  const catalogs = [], ids = new Set();
  for (const row of data) {
    if (!record(row) || typeof row.access !== 'string') throw new Error('Invalid directory listing/access field.');
    if (row.access !== 'public') continue;
    if (!Number.isSafeInteger(row.id) || row.id <= 0 || typeof row.isApi !== 'boolean' ||
        ['slug', 'title', 'url'].some(key => typeof row[key] !== 'string' || !row[key].trim() || [...row[key]].length > 8192 || /[\uD800-\uDFFF]/u.test(row[key]))) {
      throw new Error('Invalid public directory listing fields.');
    }
    if (ids.has(row.id)) throw new Error('Duplicate public directory listing ID.');
    ids.add(row.id); catalogs.push(Object.fromEntries(fields.map(key => [key, row[key]])));
  }
  if (!catalogs.length) throw new Error('Directory contains no public listings.');
  return catalogs.sort((a, b) => compare(alphabetical(a.title), alphabetical(b.title)) || compare(a.url, b.url) || a.id - b.id);
}

export function normalizeSnapshot(data) {
  if (!record(data) || data.source !== DIRECTORY_SOURCE || data.api !== DIRECTORY_API ||
      typeof data.fetched_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(data.fetched_at) || !Number.isFinite(Date.parse(data.fetched_at))) {
    throw new Error('Invalid directory source or retrieval date.');
  }
  return {...data, catalogs: normalizeCatalogs(data.catalogs)};
}

export function endpointProblem(url) {
  if (/^http:\/\//i.test(url)) return 'This listing advertises HTTP. Browser connections require HTTPS; the URL has not been changed.';
  if (!/^[a-z][a-z\d+.-]*:/i.test(url)) return 'This listing has no URL scheme. An explicit HTTPS URL is required; the URL has not been changed.';
  if (!/^https:\/\/(?:\[[0-9a-f:.]+\]|[^:/?#@]+)(?::\d+)?(?:[/?#]|$)/i.test(url) || /[\s\\\u0000-\u001f\u007f]/u.test(url)) return 'This listing has an unsupported or unsafe URL. An HTTPS URL without credentials is required.';
  try { safeURL(url, undefined, true); return ''; }
  catch { return 'This listing has an invalid or unsafe URL. An HTTPS URL without credentials is required.'; }
}

export function filterCatalogs(catalogs, term) {
  const query = term.trim().toLowerCase();
  return catalogs.filter(row => `${row.title}\n${row.url}`.toLowerCase().includes(query));
}

export async function refreshDirectory(fetcher = fetch) {
  const {data} = await fetchJSON({url: DIRECTORY_API}, fetcher);
  return {source: DIRECTORY_SOURCE, api: DIRECTORY_API, fetched_at: new Date().toISOString(), catalogs: normalizeCatalogs(data)};
}

export function createDirectoryChooser(changed) {
  const $ = id => document.getElementById(id);
  let directory = null, selected = null, pending = false, loading = true, providerBusy = false;
  const key = row => JSON.stringify([row.id, row.url]);
  function controls() {
    $('directory-refresh').disabled = loading || pending || providerBusy;
    $('directory-filter').disabled = $('directory-catalog').disabled = pending || providerBusy || !directory;
  }
  function render() {
    const matches = directory ? filterCatalogs(directory.catalogs, $('directory-filter').value) : [];
    const select = $('directory-catalog');
    select.replaceChildren(new Option('Choose a public listing', ''));
    const retained = selected && !matches.some(row => key(row) === key(selected));
    if (retained) select.add(new Option(`${selected.title} · retained selection`, key(selected)));
    for (const row of matches) select.add(new Option(`${row.title} · ${row.isApi ? 'API' : 'Static catalog'}`, key(row)));
    select.value = selected ? key(selected) : '';
    $('directory-count').textContent = directory ? `${matches.length} of ${directory.catalogs.length} public listings${retained ? ' · selected endpoint retained' : ''}` : 'No directory loaded.';
    $('directory-date').textContent = directory ? `Directory fetched ${directory.fetched_at}` : '';
    controls();
  }
  function selectionDetails() {
    $('directory-detail').hidden = !selected;
    if (!selected) return;
    $('directory-type').textContent = selected.isApi ? 'STAC API listing' : 'Static catalog listing';
    $('directory-url').textContent = selected.url;
    $('directory-source').href = `https://stacindex.org/catalogs/${encodeURIComponent(selected.slug)}`;
    $('directory-problem').textContent = endpointProblem(selected.url) || 'HTTPS endpoint. Browser CORS and provider availability are checked when you connect.';
  }
  $('directory-filter').oninput = render;
  $('directory-filter').onkeydown = event => {
    if (event.key === 'Enter') event.preventDefault(); // Filtering never submits Connect.
  };
  $('directory-catalog').onchange = () => {
    const value = $('directory-catalog').value;
    selected = directory.catalogs.find(row => key(row) === value) || (selected && key(selected) === value ? selected : null);
    selectionDetails(); changed(true);
  };
  $('directory-refresh').onclick = async () => {
    if (loading || pending || providerBusy) return;
    pending = true; controls(); changed();
    $('directory-status').textContent = 'Refreshing from STAC Index…';
    try {
      directory = await refreshDirectory();
      if (selected) selected = directory.catalogs.find(row => key(row) === key(selected)) || selected;
      render(); selectionDetails();
      $('directory-status').textContent = 'Directory refreshed. Your selected endpoint and current connection are unchanged.';
    } catch (error) { $('directory-status').textContent = `Refresh failed. Directory and connection unchanged. ${error.message}`; }
    finally { pending = false; controls(); changed(); }
  };
  return {
    get selection() { return selected; },
    get pending() { return pending; },
    setBusy(value) { providerBusy = value; controls(); },
    async load() {
      try {
        const {data} = await fetchJSON({url: new URL('./public-catalogs.json', import.meta.url).href});
        directory = normalizeSnapshot(data); render();
        $('directory-status').textContent = 'Bundled directory ready. Refresh only when you want current listings.';
      } catch (error) { render(); $('directory-status').textContent = `Bundled directory unavailable. Presets and custom HTTPS still work. ${error.message}`; }
      loading = false; controls(); changed();
    },
  };
}
