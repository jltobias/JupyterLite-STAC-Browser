import {STACClient, PRESETS, safeURL, localToday, earliestCollectionDate, copernicusDownloadAccess} from './stac.js';
import {StudyArea} from './study-area.js';
import {createDirectoryChooser, endpointProblem} from './catalog-directory.js';
const $ = id => document.getElementById(id);
const client = new STACClient();
L.PM.setOptIn(true);
const map = L.map('map', {worldCopyJump: true, pmIgnore: false}).setView([-2, 32], 5);
for (const [name, z] of [['coverage', 390], ['footprints', 410], ['study', 430]]) map.createPane(name).style.zIndex = z;
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);
const footprints = L.featureGroup().addTo(map);
let itemLayers = new WeakMap();
let busy = false, connected = false;
let startEdited = false;
const directory = createDirectoryChooser(selectionChanged => {
  if (selectionChanged && $('preset').value === 'directory') $('endpoint').value = directory.selection?.url || '';
  controls();
});
function queryChanged() {
  if (client.query) $('result-context').textContent = 'Search settings changed. Displayed results and exports still describe the completed search. Select Search to refresh them.';
}
const study = new StudyArea(map, {status, changed: queryChanged});
function el(tag, text, className) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n; }
function status(text, error = false) { $('status').textContent = text; $('status').className = error ? 'error' : ''; }
function controls() {
  study.setBusy(busy);
  $('start').disabled = $('end').disabled = $('limit').disabled = busy;
  const fromDirectory = $('preset').value === 'directory';
  directory.setBusy(busy);
  $('preset').disabled = $('endpoint').disabled = busy;
  $('endpoint').readOnly = fromDirectory;
  $('connect').disabled = busy || directory.pending || (fromDirectory && (!directory.selection || Boolean(endpointProblem(directory.selection.url))));
  $('more').disabled = busy || !connected || !client.next;
  $('more-collections').disabled = busy || !connected || !client.collectionNext;
  $('collection').disabled = busy || !connected;
  $('search').disabled = busy || !connected || !client.searchLink;
  $('export-geojson').disabled = $('export-query').disabled = busy || !client.items.length;
}
async function run(action) {
  if (busy) return;
  busy = true; controls();
  try { await action(); } catch (error) { status(error.message, true); }
  finally { busy = false; controls(); }
}
function collectionOptions() {
  const selected = $('collection').value;
  $('collection').replaceChildren(new Option('All collections', ''));
  const options = client.collections.map(c => {
    const title = typeof c.title === 'string' && c.title.trim() ? c.title.trim() : c.id;
    return new Option(title === c.id ? c.id : `${title} — ${c.id}`, c.id);
  });
  options.sort((a, b) => a.text.localeCompare(b.text, undefined, {sensitivity: 'base', numeric: true}));
  for (const option of options) $('collection').add(option);
  $('collection').value = client.collections.some(c => c.id === selected) ? selected : '';
  $('more-collections').hidden = !client.collectionNext || client.collections.length >= 1000;
}
function dateDefaults(reset = true) {
  const selected = $('collection').value;
  // At the list limit, an absent next link does not prove discovery is complete.
  const incomplete = client.collectionNext || client.collections.length >= 1000;
  const collections = selected ? client.collections.filter(c => c.id === selected) : (incomplete ? [] : client.collections);
  if (reset || !startEdited) $('start').value = earliestCollectionDate(collections);
  if (reset) { $('end').value = localToday(); startEdited = false; }
}
$('collection').onchange = () => {
  dateDefaults();
  const collection = client.collections.find(c => c.id === $('collection').value);
  study.showCollection(collection, Boolean(client.searchLink)); queryChanged();
};
$('start').oninput = () => { startEdited = true; queryChanged(); };
for (const id of ['end', 'limit', 'bbox']) $(id).addEventListener('input', queryChanged);
async function connect(url) {
  connected = false; client.reset(); renderResults(); collectionOptions(); dateDefaults(); controls();
  study.showCollection(null); $('result-context').textContent = '';
  $('metadata').replaceChildren(el('p', 'Select a footprint or an item to inspect its metadata.', 'empty'));
  status('Connecting to catalog…'); $('catalog-links').replaceChildren();
  $('catalog-summary').textContent = 'Connecting…';
  try { await client.connect(url); }
  catch (error) { $('catalog-summary').textContent = 'Connection unavailable. Check the URL or try another catalog.'; throw error; }
  connected = true;
  // Keep an advertised directory URL verbatim, even when its provider redirects.
  if ($('preset').value !== 'directory' || directory.selection?.url !== url) {
    $('endpoint').value = client.url;
    if ($('preset').value === 'directory') { $('preset').value = 'custom'; $('directory-panel').hidden = true; }
  }
  collectionOptions(); dateDefaults();
  $('catalog-summary').textContent = `${client.root.title || client.root.id} · ${client.collections.length} collections loaded${client.searchLink ? '' : ' · Static catalog: remote Item Search is not advertised.'}`;
  for (const link of client.catalogLinks()) {
    const button = el('button', `${link.rel} · ${link.title || link.href}`);
    button.type = 'button';
    button.onclick = () => run(async () => {
      if (link.rel === 'item') { await client.openItem(link); renderResults(); select(client.items[0]); status('Loaded one static STAC Item.'); }
      else await connect(safeURL(link.href, client.url, true));
    });
    $('catalog-links').append(button);
  }
  status(client.searchLink ? 'Connected. Choose a collection or search all collections in this area.' : 'Static catalog connected. Browse child or item links above; remote search is unavailable.');
}
$('preset').onchange = () => {
  const preset = PRESETS[$('preset').value], fromDirectory = $('preset').value === 'directory';
  $('directory-panel').hidden = !fromDirectory;
  if (preset) $('endpoint').value = preset[1];
  else if (fromDirectory) $('endpoint').value = directory.selection?.url || '';
  else { $('endpoint').value = ''; $('endpoint').focus(); }
  controls();
};
$('connect-form').onsubmit = event => {
  event.preventDefault();
  if ($('connect').disabled) return;
  run(() => connect($('endpoint').value));
};
$('search-form').onsubmit = event => {
  event.preventDefault();
  if (busy) return;
  let spatial;
  try { spatial = study.searchParameters(); }
  catch (error) { status(error.message, true); return; }
  run(async () => {
  status('Searching metadata…');
  await client.search({...spatial, collection: $('collection').value, start: $('start').value, end: $('end').value, limit: $('limit').value});
  study.setEditing(false);
  $('result-context').textContent = `Completed search: ${client.provenance().spatial_mode === 'none' ? 'no study-area spatial filter' : client.query.intersects ? 'exact polygon' : 'bounding box'}. Results and exports describe this query.`;
  $('metadata').replaceChildren(el('p', 'Select one of the new results to inspect its metadata.', 'empty'));
  renderResults();
  status(client.items.length ? `${client.items.length} items loaded. Select an item to inspect its assets.${client.next ? ' Another page is available.' : ''}` : 'No items match this area and date range. Try a larger area or remove the date filter.');
}); };
$('more').onclick = () => run(async () => { status('Loading next page…'); await client.more(); renderResults(); status(`${client.items.length} unique items loaded (maximum 500).`); });
$('more-collections').onclick = () => run(async () => { await client.moreCollections(); collectionOptions(); dateDefaults(false); queryChanged(); status(`${client.collections.length} collections loaded (maximum 1000).`); });
function renderResults() {
  $('results').replaceChildren(); footprints.clearLayers(); $('count').textContent = client.items.length;
  itemLayers = new WeakMap();
  $('more').hidden = !client.next;
  if (!client.items.length) $('results').append(el('p', 'No items loaded. Connect to a catalog, choose an area, and search.', 'empty'));
  for (const item of client.items) {
    const button = el('button', null, 'result-card');
    button.append(el('strong', item.properties?.title || item.id), el('small', `${item.collection || 'STAC Item'} · ${item.properties?.datetime || item.properties?.start_datetime || 'Date not specified'}`));
    button.onclick = () => select(item, button); $('results').append(button);
    if (item.geometry) {
      try {
        const layer = L.geoJSON(item, {pane: 'footprints', pmIgnore: true, style: {color: '#386a4e', weight: 1.7, fillColor: '#c0d981', fillOpacity: 0, className: 'result-footprint'}, pointToLayer: (_, latlng) => L.circleMarker(latlng, {pane: 'footprints', pmIgnore: true, radius: 7, color: '#386a4e', fillOpacity: 0, className: 'result-footprint'})});
        layer.on('click', () => { select(item, button); button.scrollIntoView({block: 'nearest'}); });
        layer.bindTooltip(el('span', item.properties?.title || item.id)); footprints.addLayer(layer);
        itemLayers.set(item, layer);
      } catch { /* Invalid provider geometry does not hide its metadata. */ }
    }
  }
}
function addLink(parent, text, href, base) {
  try { const a = el('a', text); a.href = safeURL(href, base); a.target = '_blank'; a.rel = 'noopener noreferrer'; parent.append(a); return a; }
  catch { parent.append(el('span', `${text} (unsafe link omitted)`)); }
}
function datasetDownloads(item) {
  const section = el('section', null, 'dataset-downloads');
  section.setAttribute('aria-labelledby', 'download-heading');
  const heading = el('h3', 'Download dataset'); heading.id = 'download-heading';
  section.append(heading);
  const assets = el('ul', null, 'download-assets'), base = client.baseFor(item);
  let fileLinks = 0, restrictedFileLinks = 0, otherRestrictedAssets = false, copernicusLinks = 0, copernicusDataLinks = 0;
  const collection = client.collections.find(c => c.id === item.collection);
  const entries = Object.entries(item.assets || {}).filter(([, asset]) => asset && typeof asset === 'object' && typeof asset.href === 'string');
  // Put explicitly advertised data before previews and other supporting assets.
  const hasDataRole = asset => Array.isArray(asset.roles) && asset.roles.includes('data');
  entries.sort(([, a], [, b]) => Number(hasDataRole(b)) - Number(hasDataRole(a)));
  for (const [key, asset] of entries) {
    const li = el('li'), roles = Array.isArray(asset.roles) ? asset.roles.filter(r => typeof r === 'string') : [];
    const supporting = !roles.includes('data') && roles.some(r => ['thumbnail', 'overview', 'metadata'].includes(r));
    let href = asset.href, label = asset.title || key, access = asset;
    try { if (!href.trim()) throw new Error('Empty asset URL'); href = safeURL(href, base); }
    catch {
      const alternatives = asset.alternate && typeof asset.alternate === 'object' ? asset.alternate : {};
      for (const alternative of [alternatives.https, ...Object.values(alternatives)]) {
        if (typeof alternative?.href !== 'string' || !alternative.href.trim()) continue;
        try { href = safeURL(alternative.href, base, true); label += ' (HTTPS)'; access = alternative; break; }
        catch { /* Unsupported or unsafe URLs stay non-clickable. */ }
      }
    }
    li.append(el('strong', label));
    li.append(el('small', `${asset.type || 'type unspecified'}${roles.length ? ' · ' + roles.join(', ') : ''}`));
    const copernicus = copernicusDownloadAccess(href, item, base);
    const auth = Boolean(copernicus) || (Array.isArray(access['auth:refs']) && access['auth:refs'].length > 0);
    if (auth) {
      if (!copernicus) otherRestrictedAssets = true;
      li.append(el('small', 'Provider authentication required'));
      for (const ref of Array.isArray(access['auth:refs']) ? access['auth:refs'] : []) {
        if (typeof ref !== 'string') continue;
        const scheme = item.properties?.['auth:schemes']?.[ref] || collection?.['auth:schemes']?.[ref];
        if (typeof scheme?.description === 'string') li.append(el('small', scheme.description));
      }
    }
    if (copernicus) {
      copernicusLinks++;
      if (!supporting) copernicusDataLinks++;
      const link = addLink(li, supporting ? 'Open in Copernicus ↗' : 'Open in Copernicus to download ↗', copernicus.browserURL);
      link.className = `${supporting ? 'asset-supporting' : 'asset-download'} asset-provider`;
      link.setAttribute('aria-label', `Open ${label} in Copernicus to download (sign-in required)`);
      li.append(el('small', copernicus.itemSpecific
        ? `Log in there, find “${asset.title || key}” (expand if needed), select HTTPS if offered, then Download.`
        : `Log in there and search for Item “${item.id}” in collection “${item.collection || 'not specified'}”. Find “${asset.title || key}” (expand if needed), select HTTPS if offered, then Download.`));
      const address = el('input'); address.type = 'text'; address.readOnly = true; address.value = safeURL(href, base, true);
      address.setAttribute('aria-label', `${label} authenticated API URL`);
      address.addEventListener('focus', () => address.select());
      li.append(el('small', 'For authenticated API clients: copy this URL and send an Authorization: Bearer header.'), address);
    } else if (/^s3:/i.test(href)) {
      li.append(el('small', 'S3; use a compatible client with the asset address below.'));
      const address = el('input'); address.type = 'text'; address.readOnly = true; address.value = href;
      address.setAttribute('aria-label', `${label} asset address`);
      address.addEventListener('focus', () => address.select()); li.append(address);
    } else {
      const actionLabel = String(label).replace(/^download\s*[-:–—]\s*/i, '');
      const link = href.trim() ? addLink(li, `${supporting ? 'Open' : 'Download'} ${actionLabel}`, href, base) : null;
      if (!href.trim()) li.append(el('small', 'No asset address supplied.'));
      if (link) {
        link.className = supporting ? 'asset-supporting' : 'asset-download';
        if (!supporting) { link.setAttribute('download', ''); fileLinks++; if (auth) restrictedFileLinks++; }
      }
    }
    assets.append(li);
  }
  section.append(el('p', copernicusDataLinks
    ? 'Copernicus downloads require sign-in. Open the dataset in the official Copernicus STAC browser, log in, and expand the named asset. Select HTTPS if offered, then Download. Opening the raw API URL alone returns 401 Unauthorized. Files contain the full asset, not a study-area clip.'
    : fileLinks
    ? `${fileLinks === restrictedFileLinks ? 'These data links require provider authentication.' : 'Choose a file below.'} Files open at the provider; if displayed, use your browser’s Save option. Downloads contain the full asset, not a study-area clip.`
    : 'No browser-downloadable data file is advertised. Check the asset instructions and Source links below for provider access.', 'download-help'));
  if (copernicusLinks) {
    if (!copernicusDataLinks) section.append(el('p', 'Copernicus supporting files require sign-in. Open them in the provider browser and follow the instructions beside each file.', 'download-help'));
    const help = el('p', null, 'download-help');
    addLink(help, 'Copernicus sign-in and download instructions ↗', 'https://documentation.dataspace.copernicus.eu/APIs/OData.html#product-download');
    section.append(help);
  }
  if (otherRestrictedAssets) section.append(el('p', 'This browser does not sign in or sign URLs. Follow the provider’s access instructions; item metadata can still be saved below.', 'download-help'));
  if (assets.children.length) section.append(assets);
  else section.append(el('p', 'No assets supplied.'));
  const metadata = el('button', 'Download item metadata (.json)', 'metadata-download'); metadata.type = 'button';
  metadata.onclick = () => download('stac-item.json', item);
  section.append(metadata, el('p', 'Original STAC metadata only; dataset files are separate.', 'hint'));
  return section;
}
function select(item, button) {
  footprints.eachLayer(layer => layer.setStyle({color: '#386a4e', weight: 1.7, fillOpacity: 0}));
  const layer = itemLayers.get(item);
  if (layer) { layer.setStyle({color: '#b56c28', weight: 3, fillOpacity: .12}); layer.bringToFront(); if (layer.getBounds().isValid()) map.fitBounds(layer.getBounds(), {maxZoom: 9, padding: [20, 20]}); }
  document.querySelectorAll('.result-card').forEach(n => n.classList.remove('selected')); button?.classList.add('selected');
  const panel = $('metadata'); panel.replaceChildren(el('h3', item.properties?.title || item.id), datasetDownloads(item));
  const props = item.properties || {};
  panel.append(el('p', props.description || 'No item description supplied.'));
  const collection = client.collections.find(c => c.id === item.collection);
  const providerNames = providers => (Array.isArray(providers) ? providers : []).filter(p => p && typeof p.name === 'string').map(p => p.name).join(', ');
  const providers = providerNames(props.providers) || providerNames(collection?.providers) || 'Not supplied — consult provider';
  const dl = el('dl');
  for (const [key, value] of Object.entries({ID: item.id, Collection: item.collection || 'Not specified', Date: props.datetime || `${props.start_datetime || 'Unknown'} / ${props.end_datetime || 'Unknown'}`, 'Reference year': props.year ?? 'Not specified', Project: props.project || 'Not specified', License: props.license || collection?.license || 'Not supplied — consult provider', Providers: providers})) { dl.append(el('dt', key), el('dd', String(value))); }
  panel.append(dl);
  panel.append(el('h3', 'Source links'));
  const sourceLinks = el('ul');
  for (const link of Array.isArray(item.links) ? item.links : []) {
    if (!link || typeof link !== 'object' || typeof link.href !== 'string') continue;
    const li = el('li');
    try { addLink(li, link.title || link.rel, client.linkURL(item, link)); }
    catch { li.append(el('span', `${link.title || link.rel} (unsafe link omitted)`)); }
    sourceLinks.append(li);
  }
  panel.append(sourceLinks);
  const raw = el('details'); raw.append(el('summary', 'Full original item JSON'), el('pre', JSON.stringify(item, null, 2))); panel.append(raw);
}
function download(name, value) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}));
  const link = el('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('export-geojson').onclick = () => download('stac-items.geojson', client.geojson());
$('export-query').onclick = () => download('stac-search.json', client.provenance());
run(() => connect(PRESETS.worldpop[1]));
directory.load();
