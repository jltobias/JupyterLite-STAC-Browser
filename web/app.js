import {STACClient, PRESETS, safeURL, localToday, earliestCollectionDate, copernicusDownloadAccess} from './stac.js';
import {StudyArea} from './study-area.js';
import {createDirectoryChooser, endpointProblem} from './catalog-directory.js';
import {startRasterClip} from './raster-clip.js';
import {copernicusSubset} from './copernicus-subset.js';
import {CopernicusSession, isProtectedURL, readProtectedRange, downloadOriginal, originalFilename} from './copernicus-session.js';
import {buildFieldworkSelection, assessFieldworkRaster, buildFieldworkRasterHandoff, sanitizeExport, sanitizedURL} from './fieldwork-handoff.js';
import {rustGISAssetHandoff, rustGISItemHandoff, rustGISLocalFileHandoff} from './rustgis-handoff.js';
import {geoLibreAssetHandoff, geoLibreBridgeURL} from './geolibre-handoff.js';
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
let cropJob = null, cropSelection = 0, cropRefreshPending = false, cropRustGISWindow = null;
let selectedItem = null;
const copernicusSession = new CopernicusSession(message => {
  $('copernicus-token').value = '';
  $('copernicus-status').textContent = message + (copernicusSession.loaded ? ` Session ends by ${new Date(copernicusSession.expiresAt).toLocaleTimeString()}.` : '');
  if (selectedItem) {
    const current = document.querySelector('.dataset-downloads'), updated = datasetDownloads(selectedItem);
    // Preserve public asset nodes and their active crop handlers in mixed items.
    for (const row of current?.querySelectorAll('[data-session-asset]') || []) {
      const replacement = [...updated.querySelectorAll('[data-session-asset]')].find(node => node.dataset.sessionAsset === row.dataset.sessionAsset);
      if (replacement) row.replaceWith(replacement);
    }
    const help = updated.querySelector('.session-download-help');
    if (help) current?.querySelector('.session-download-help')?.replaceWith(help);
    // Keep a running public crop attached. Refresh its candidate controls as
    // soon as the worker settles, preserving any completed result controls.
    if (cropJob) cropRefreshPending = true;
    else replaceCropWorkflow(current, updated);
    queueMicrotask(updateCropBounds);
  }
});
$('copernicus-form').onsubmit = event => {
  event.preventDefault();
  try { copernicusSession.load($('copernicus-token').value); }
  catch (error) { $('copernicus-status').textContent = error.message; }
  finally { $('copernicus-token').value = ''; }
};
$('copernicus-clear').onclick = () => copernicusSession.clear();
addEventListener('pagehide', () => { closeRustGISWindow(cropRustGISWindow); copernicusSession.clear(); cancelCrop(); });
function cancelCrop(message = 'Crop canceled because the selection or settings changed. No file was saved.') {
  closeRustGISWindow(cropRustGISWindow);
  copernicusSession.cancelJobs();
  cropJob?.cancel(message); cropJob = null;
}
const directory = createDirectoryChooser(selectionChanged => {
  if (selectionChanged) cancelCrop();
  if (selectionChanged && $('preset').value === 'directory') $('endpoint').value = directory.selection?.url || '';
  controls();
});
function queryChanged() {
  cancelCrop();
  queueMicrotask(updateCropBounds);
  if (client.query) $('result-context').textContent = 'Search settings changed. Displayed results and exports still describe the completed search. Select Search to refresh them.';
}
const study = new StudyArea(map, {status, changed: queryChanged});
function el(tag, text, className) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n; }
function replaceCropWorkflow(current, updated) {
  const previous = current?.querySelector('.clip-workflow'), workflow = updated?.querySelector('.clip-workflow');
  if (!previous || !workflow) return;
  const priorStatus = previous.querySelector('.crop-status'), nextStatus = workflow.querySelector('.crop-status');
  if (priorStatus?.hasChildNodes() && nextStatus) nextStatus.replaceWith(priorStatus);
  previous.replaceWith(workflow);
}
function refreshCropWorkflow() {
  if (!selectedItem) return;
  replaceCropWorkflow(document.querySelector('.dataset-downloads'), datasetDownloads(selectedItem));
  queueMicrotask(updateCropBounds);
}
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
  cancelCrop(); cropSelection++; selectedItem = null;
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
      cancelCrop(); cropSelection++;
      if (link.rel === 'item') { await client.openItem(link); renderResults(); select(client.items[0]); status('Loaded one static STAC Item.'); }
      else await connect(safeURL(link.href, client.url, true));
    });
    $('catalog-links').append(button);
  }
  status(client.searchLink ? 'Connected. Choose a collection or search all collections in this area.' : 'Static catalog connected. Browse child or item links above; remote search is unavailable.');
}
$('preset').onchange = () => {
  cancelCrop();
  const preset = PRESETS[$('preset').value], fromDirectory = $('preset').value === 'directory';
  $('directory-panel').hidden = !fromDirectory;
  if (preset) $('endpoint').value = preset[1];
  else if (fromDirectory) $('endpoint').value = directory.selection?.url || '';
  else { $('endpoint').value = ''; $('endpoint').focus(); }
  controls();
};
$('endpoint').addEventListener('input', () => cancelCrop());
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
  cancelCrop(); cropSelection++;
  status('Searching metadata…');
  await client.search({...spatial, collection: $('collection').value, start: $('start').value, end: $('end').value, limit: $('limit').value});
  // Old-item controls remain usable while search awaits. Invalidate those jobs too.
  cancelCrop(); cropSelection++;
  selectedItem = null;
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
  let refreshedSelection;
  if (!client.items.length) $('results').append(el('p', 'No items loaded. Connect to a catalog, choose an area, and search.', 'empty'));
  for (const item of client.items) {
    const button = el('button', null, 'result-card');
    button.append(el('strong', item.properties?.title || item.id), el('small', `${item.collection || 'STAC Item'} · ${item.properties?.datetime || item.properties?.start_datetime || 'Date not specified'}`));
    button.onclick = () => select(item, button); $('results').append(button);
    if (selectedItem && item.id === selectedItem.id &&
        (typeof item.collection === 'string' ? item.collection : '') === (typeof selectedItem.collection === 'string' ? selectedItem.collection : '')) refreshedSelection = {item, button};
    if (item.geometry) {
      try {
        const layer = L.geoJSON(item, {pane: 'footprints', pmIgnore: true, style: {color: '#386a4e', weight: 1.7, fillColor: '#c0d981', fillOpacity: 0, className: 'result-footprint'}, pointToLayer: (_, latlng) => L.circleMarker(latlng, {pane: 'footprints', pmIgnore: true, radius: 7, color: '#386a4e', fillOpacity: 0, className: 'result-footprint'})});
        layer.on('click', () => { select(item, button); button.scrollIntoView({block: 'nearest'}); });
        layer.bindTooltip(el('span', item.properties?.title || item.id)); footprints.addLayer(layer);
        itemLayers.set(item, layer);
      } catch { /* Invalid provider geometry does not hide its metadata. */ }
    }
  }
  if (refreshedSelection) {
    const {item, button} = refreshedSelection;
    if (item !== selectedItem) select(item, button, false);
    else highlightSelection(item, button, false);
  }
}
function addLink(parent, text, href, base) {
  try { const a = el('a', text); a.href = safeURL(href, base); a.target = '_blank'; a.rel = 'noopener noreferrer'; parent.append(a); return a; }
  catch { parent.append(el('span', `${text} (unsafe link omitted)`)); }
}
function updateCropBounds() {
  const label = document.querySelector('.crop-bounds');
  if (!label) return;
  try { const area = study.clipSnapshot(); label.textContent = `Current study bbox (W/S/E/N): ${area.bbox.join(', ')}${area.shape === 'polygon' ? ' · polygon envelope' : ''}. Used in every search mode.`; }
  catch (error) { label.textContent = error.message; }
}
function saveBlob(name, blob) {
  const url = URL.createObjectURL(blob), link = el('a'); link.href = url; link.download = name;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
}
function cropOption(li, {item, key, asset, href, supporting, auth, copernicus, authURL}) {
  const authenticated = Boolean(authURL && copernicusSession.loaded);
  if (Array.isArray(asset.roles) && asset.roles.some(role => ['thumbnail', 'overview'].includes(role))) {
    li.append(el('small', 'Bbox clipping unavailable for previews and overviews; these are not source raster data.', 'clip-unavailable'));
    return null;
  }
  const subset = copernicus ? copernicusSubset(item, key, asset) : null;
  if (subset?.unavailable) { li.append(el('small', subset.unavailable, 'clip-unavailable')); if (!authenticated || /netcdf/i.test(subset.unavailable)) return null; }
  if (subset?.create && !supporting) {
    li.append(el('small', `Provider bbox subset: NDVI 300m V2 · ${subset.date} · raw ${subset.band} (${subset.sampleType}). Sign-in required; Analytical GeoTIFF only.`, 'subset-help'));
    const prepare = el('button', 'Prepare Copernicus bbox subset', 'provider-subset'); prepare.type = 'button';
    const result = el('div', null, 'provider-subset-result');
    prepare.onclick = () => {
      result.replaceChildren();
      try {
        const area = study.clipSnapshot(), plan = subset.create(area.bbox);
        result.append(el('small', `Frozen bbox: ${area.bbox.join(', ')}. Date: ${subset.date}; band: ${subset.band}.`));
        const aoi = el('button', 'Download bbox AOI (.geojson)'); aoi.type = 'button'; aoi.onclick = () => download('study-bbox.geojson', plan.aoi);
        result.append(aoi); addLink(result, 'Open mapped dataset and date in Copernicus ↗', plan.url);
        result.append(el('small', 'The link sets the map view, date and raw-band script; it cannot carry the AOI. Sign in, import the downloaded GeoJSON with the Area of Interest upload control, then Image Download → Analytical → GeoTIFF. Select the custom script, original/native resolution and suitable CRS; verify the date and band. Provider export may resample/regrid and has size limits; its output is not guaranteed to match a source-pixel window. A rendered preview is not source data. If the exact date/product is unavailable, keep the original download.'));
      } catch (error) { result.append(el('small', error.message, 'error')); }
    };
    li.append(prepare, result); if (!authenticated) return null;
  }
  let validURL = false;
  try { href = safeURL(href); validURL = true; } catch { /* Preserve the existing access instructions. */ }
  const netcdf = /netcdf|\.nc(?:\b|$)/i.test(`${asset.type || ''} ${href}`);
  const tiff = /(?:image\/(?:tiff|geotiff)|application\/geotiff)/i.test(asset.type || '') || /\.tiff?(?:[/?#)]|$)/i.test(href);
  if (supporting || !validURL || (auth && !authenticated) || !tiff || netcdf || (Array.isArray(asset.roles) && asset.roles.includes('archive'))) {
    li.append(el('small', netcdf ? 'NetCDF clipping unavailable: no verified NetCDF subset route is available. Keep the original .nc download; no GeoTIFF conversion is offered.' : auth ? 'Bbox clipping unavailable here: provider authentication or signing is required; use its access workflow.' : supporting ? 'Bbox clipping unavailable for previews and metadata; these are not source raster data.' : 'Bbox clipping unavailable for this format or access URL. Keep the original file download.', 'clip-unavailable'));
    return null;
  }
  li.append(el('small', 'This raster is available in the Clip study bbox workflow above.', 'clip-available'));
  return {item, key, asset, href, authURL, authenticated, label: asset.title || key};
}

function beginRustGISWindow() {
  const handoff = rustGISLocalFileHandoff();
  const state = {handoff, popup: null, marker: `${Date.now()}-${Math.random()}`};
  try { state.popup = window.open('about:blank', '_blank'); }
  catch { return state; }
  if (state.popup) {
    try {
      const popup = state.popup;
      popup.document.title = 'Preparing clipped GeoTIFF for RustGIS';
      popup.document.body.textContent = 'Preparing and downloading the clipped GeoTIFF…';
      popup.document.body.dataset.stacClipPlaceholder = state.marker;
      popup.opener = null;
    } catch {
      try { state.popup.close(); } catch { /* The partially opened tab may already be inaccessible. */ }
      state.popup = null;
    }
  }
  return state;
}

function ownsRustGISWindow(state) {
  if (!state?.popup || state.popup.closed) return false;
  try {
    return state.popup.location.href === 'about:blank' &&
      state.popup.document.body?.dataset.stacClipPlaceholder === state.marker;
  } catch { return false; }
}

function closeRustGISWindow(state) {
  try { if (ownsRustGISWindow(state)) state.popup.close(); } catch { /* The popup may already be cross-origin. */ }
  if (cropRustGISWindow === state) cropRustGISWindow = null;
}

function finishRustGISWindow(state) {
  if (!ownsRustGISWindow(state)) { if (cropRustGISWindow === state) cropRustGISWindow = null; return false; }
  try {
    state.popup.location.replace(state.handoff.href);
    if (cropRustGISWindow === state) cropRustGISWindow = null;
    return true;
  } catch { if (cropRustGISWindow === state) cropRustGISWindow = null; return false; }
}

function promotedCropWorkflow(candidates) {
  const workflow = el('section', null, 'clip-workflow');
  workflow.setAttribute('aria-labelledby', 'clip-workflow-heading');
  const heading = el('h4', 'Clip study bbox'); heading.id = 'clip-workflow-heading';
  workflow.append(heading, el('p', '', 'crop-bounds'), el('p', 'Create a source-resolution GeoTIFF on the source pixel grid. Raster transfer starts only when you choose an action. Browser limits: 64 MiB output, 128 MiB transfer/decoded blocks, 16 MiB per block and two minutes per job.', 'download-help'));
  if (!candidates.length) {
    workflow.append(el('p', 'No directly clip-eligible GeoTIFF is available for this Item. See each asset below for format, authentication, or provider-subset guidance.', 'clip-unavailable'));
    return workflow;
  }
  let chooser = null;
  if (candidates.length > 1) {
    const label = el('label', 'Raster asset to clip');
    chooser = el('select'); chooser.setAttribute('aria-label', 'Raster asset to clip');
    candidates.forEach((candidate, index) => chooser.append(new Option(`${candidate.label} (${candidate.key})`, String(index))));
    label.append(chooser); workflow.append(label);
  } else workflow.append(el('p', `Raster asset: ${candidates[0].label} (${candidates[0].key})`, 'clip-asset-summary'));
  const actions = el('div', null, 'clip-actions');
  const clip = el('button', 'Clip & download GeoTIFF', 'asset-clip');
  const rustgis = el('button', 'Clip, download & open RustGIS', 'asset-clip-rustgis');
  const cancel = el('button', 'Cancel crop', 'crop-cancel');
  const message = el('p', '', 'crop-status');
  for (const button of [clip, rustgis]) { button.type = 'button'; button.dataset.cropAction = ''; button.disabled = Boolean(cropJob); }
  cancel.type = 'button'; cancel.hidden = true;
  cancel.onclick = () => cancelCrop('Crop canceled. No file was saved or handed to RustGIS.');
  message.setAttribute('role', 'status'); message.setAttribute('aria-live', 'polite');
  const selected = () => candidates[Number(chooser?.value || 0)];
  clip.onclick = () => performCrop(workflow, selected(), {cancel, message, chooser});
  rustgis.onclick = () => {
    const rustgisWindow = beginRustGISWindow();
    performCrop(workflow, selected(), {cancel, message, chooser, rustgisWindow});
  };
  actions.append(clip, rustgis, cancel); workflow.append(actions, message);
  return workflow;
}

async function performCrop(workflow, candidate, {cancel, message, chooser, rustgisWindow = null}) {
  if (cropJob) { closeRustGISWindow(rustgisWindow); return; }
  if (!candidate) { closeRustGISWindow(rustgisWindow); message.textContent = 'Choose a raster asset to clip.'; return; }
  if (rustgisWindow?.popup) cropRustGISWindow = rustgisWindow;
  copernicusSession.cancelJobs();
  let area;
  try { area = study.clipSnapshot(); }
  catch (error) { closeRustGISWindow(rustgisWindow); message.textContent = error.message; return; }
  const {item, key, asset, href, authURL, authenticated} = candidate;
  const selected = cropSelection, frozenText = `Frozen bbox: ${area.bbox.join(', ')}. `;
  const popupNotice = rustgisWindow && !rustgisWindow.popup
    ? ' RustGIS popup was blocked; the crop will continue and a fallback link will appear when it finishes.' : '';
  const report = text => frozenText + text + popupNotice;
  message.textContent = report('Reading raster headers…');
  document.querySelectorAll('[data-crop-action]').forEach(button => { button.disabled = true; });
  if (chooser) chooser.disabled = true;
  cancel.hidden = false;
  let job, sessionJob;
  try {
    if (authenticated) sessionJob = copernicusSession.job();
    const requestURL = authenticated ? authURL : href;
    let publicSource = null, publicItemSource = null;
    try { publicSource = sanitizedURL(requestURL, client.baseFor(item)).href; } catch { /* Worker validation reports unusable locations. */ }
    try { const source = new URL(sanitizedURL(client.sourceFor(item)).href); source.search = ''; publicItemSource = source.href; } catch { /* Retain null rather than unsafe source metadata. */ }
    job = startRasterClip({url: requestURL, bbox: area.bbox, ...(sessionJob ? {auth: sessionJob.auth()} : {}), provenance: {item_id: item.id, collection: item.collection,
      item_datetime: item.properties?.datetime, asset_key: key, asset: sanitizeExport(asset), study_area: area,
      source_url: publicSource, stac_root: sanitizeExport(client.url), item_source: publicItemSource, license: item.properties?.license || client.collections.find(c => c.id === item.collection)?.license}}, progress => {
      if (selected !== cropSelection || !workflow.isConnected || sessionJob?.signal.aborted) return;
      if (progress.phase === 'estimate') message.textContent = report(`Output: ${progress.width} × ${progress.height} pixels, EPSG:${progress.epsg}; extent ${progress.bounds.join(', ')}. About ${(progress.outputBytes / 2 ** 20).toFixed(2)} MiB plus metadata; ${progress.blocks} intersecting blocks.`);
      else if (progress.phase === 'pixels') message.textContent = report(`Reading block ${progress.completed}/${progress.blocks}; ${(progress.bytes / 2 ** 20).toFixed(2)} MiB transferred.`);
      else if (progress.phase === 'write') message.textContent = report('Writing source pixels and spatial metadata…');
    });
    cropJob = job;
    sessionJob?.signal.addEventListener('abort', () => job.cancel('Session cleared, replaced, expired, or operation canceled. No file was saved.'), {once: true});
    const result = await job.promise;
    if (cropJob !== job || selected !== cropSelection || !workflow.isConnected) { closeRustGISWindow(rustgisWindow); return; }
    sessionJob?.assert();
    const name = `${item.id}-${key}-bbox`.replace(/[^a-zA-Z0-9_.-]/g, '_').slice(0, 150);
    const filename = name + '.tif';
    saveBlob(filename, new Blob([result.buffer], {type: 'image/tiff'}));
    message.textContent = frozenText + `Prepared ${result.width} × ${result.height} pixels in EPSG:${result.epsg} and requested the browser download. Actual output extent: ${result.bounds.join(', ')}. Pixel edges align to the source grid; all supported source bands and NoData are retained.`;
    if (rustgisWindow) {
      const opened = finishRustGISWindow(rustgisWindow);
      message.append(el('small', opened
        ? `RustGIS opened in a blank project. ${rustgisWindow.handoff.instructions} File: ${filename}`
        : `The RustGIS window was blocked or closed. ${rustgisWindow.handoff.instructions} File: ${filename}`));
      if (!opened) {
        const link = addLink(message, 'Open blank RustGIS project ↗', rustgisWindow.handoff.href);
        if (link) link.className = 'rustgis-local-link';
      }
    }
    const provenance = el('button', 'Download crop provenance (.json)'); provenance.type = 'button'; provenance.onclick = () => download(name + '.json', result.provenance);
    message.append(provenance);
    const raster = {width: result.width, height: result.height, bands: result.bands, epsg: result.epsg, pixelIsArea: result.pixelIsArea,
      northUp: result.northUp, geoKeys: result.geoKeys, modelTransformation: result.modelTransformation,
      bounds: result.bounds, origin: result.origin, resolution: result.resolution};
    const fieldwork = assessFieldworkRaster({...raster, byteCount: result.buffer.byteLength});
    if (fieldwork.compatible) {
      message.append(el('small', ' FieldWork-ready: explicit WGS84/PixelIsArea GeoKeys, no ModelTransformation, a consistent north-up CRS84 grid, one band, at most 262,144 cells and 5,000,000 bytes.'));
      const sidecar = el('button', 'Download FieldWork raster handoff (.json)', 'fieldwork-raster-download'); sidecar.type = 'button';
      sidecar.onclick = async () => {
        sidecar.disabled = true;
        try {
          const handoff = await buildFieldworkRasterHandoff({buffer: result.buffer, raster, sourceLineage: result.provenance,
            fieldworkProvenance: {
              title: asset.title || item.properties?.title || String(item.id),
              provider: (Array.isArray(item.properties?.providers) ? item.properties.providers : client.collections.find(c => c.id === item.collection)?.providers || []).map(value => value?.name).filter(Boolean).join(', '),
              sourceURL: sanitizeExport(client.sourceFor(item)), downloadURL: publicSource, identifier: String(item.id),
              citation: item.properties?.citation || '', license: item.properties?.license || client.collections.find(c => c.id === item.collection)?.license || '',
              version: asset.version || item.properties?.version || '', temporalCoverage: item.properties?.datetime || item.properties?.start_datetime || '',
              published: item.properties?.published || item.properties?.created || '', accessed: result.provenance.created_at?.slice(0, 10) || '',
              units: asset['raster:bands']?.[0]?.unit || asset['eo:bands']?.[0]?.unit || '',
              notes: 'Source-resolution crop prepared by JupyterLite STAC Browser. Descriptive metadata comes from STAC declarations and is not byte or format verification.',
            },
            clippingBoundary: {crs: 'CRS84', bbox: area.bbox}, acquisitionBoundary: {crs: `EPSG:${result.epsg}`, bounds: result.bounds}});
          download(name + '-fieldwork.json', handoff);
        } catch (error) { message.append(el('small', error.message, 'error')); }
        finally { sidecar.disabled = false; }
      };
      message.append(sidecar);
    } else message.append(el('small', ` Not claimed FieldWork-ready: ${fieldwork.reasons.join('; ')}.`));
  } catch (error) {
    closeRustGISWindow(rustgisWindow);
    if (workflow.isConnected) message.textContent = frozenText + error.message;
  } finally {
    sessionJob?.finish();
    if (cropJob === job) cropJob = null;
    cancel.hidden = true;
    if (chooser) chooser.disabled = false;
    document.querySelectorAll('[data-crop-action]').forEach(button => { button.disabled = Boolean(cropJob); });
    if (!cropJob && cropRefreshPending) { cropRefreshPending = false; refreshCropWorkflow(); }
  }
}

function protectedControls(li, {href, asset, key}) {
  if (!copernicusSession.loaded) { li.append(el('small', 'Optional: load your CDSE OData access token in Copernicus connection to check or download this asset here.')); return; }
  const group = el('div', null, 'protected-controls'), message = el('p', '', 'protected-status');
  message.setAttribute('role', 'status'); message.setAttribute('aria-live', 'polite');
  const check = el('button', 'Check access and ranges', 'asset-check');
  const original = el('button', typeof window.showSaveFilePicker === 'function' ? 'Save original to file' : 'Download original (up to 128 MiB)', 'asset-original');
  const fallback = el('button', 'Browser download (up to 128 MiB)', 'asset-original-fallback');
  const cancel = el('button', 'Cancel transfer', 'transfer-cancel'); cancel.hidden = true;
  fallback.hidden = typeof window.showSaveFilePicker !== 'function';
  const buttons = [check, original, fallback]; for (const button of [...buttons, cancel]) button.type = 'button';
  let current;
  cancel.onclick = () => current?.cancel();
  const perform = async (mode, picker) => {
    cancelCrop();
    const selected = cropSelection;
    let job;
    const visible = () => selected === cropSelection && group.isConnected && current === job;
    try {
      job = copernicusSession.job(); current = job;
      buttons.forEach(button => { button.disabled = true; }); cancel.hidden = false; cancel.disabled = false;
      message.textContent = mode === 'check' ? 'Checking only this asset with bytes 0–15…' : 'Preparing original download…';
      if (mode === 'check') {
        const result = await readProtectedRange(href, job.auth(), {signal: job.signal}); job.assert();
        if (visible()) message.textContent = result.total === null
          ? 'This asset returned exactly 16 bytes with HTTP 206. Content-Range is hidden, so byte offsets cannot be independently verified. Other assets and full clipping are not verified.'
          : 'This asset returned exactly 16 bytes with HTTP 206 and verified offsets 0–15. Other assets and full clipping are not verified.';
      } else {
        // downloadOriginal invokes the picker before awaiting anything, preserving activation.
        const bytes = await downloadOriginal(href, job, {picker, filename: originalFilename(href, asset, key),
          save: (name, blob) => { job.assert(); if (visible()) saveBlob(name, blob); },
          progress: progress => {
            if (!visible() || job.signal.aborted) return;
            if (progress.phase === 'commit') { message.textContent = 'Finishing save. The completed file can no longer be canceled.'; cancel.disabled = true; }
            else message.textContent = `Received ${(progress.bytes / 2 ** 20).toFixed(2)} MiB${progress.total === null ? ' (size unknown)' : ` of ${(progress.total / 2 ** 20).toFixed(2)} MiB`}. Cancel stops this transfer.`;
          }});
        if (visible()) message.textContent = `Saved original file (${(bytes / 2 ** 20).toFixed(2)} MiB). Original bytes and format retained.`;
      }
    } catch (error) { if (visible()) message.textContent = error.message; }
    finally { job?.finish(); if (visible()) { buttons.forEach(button => { button.disabled = false; }); cancel.hidden = true; current = null; } }
  };
  check.onclick = () => perform('check');
  original.onclick = () => perform('original', typeof window.showSaveFilePicker === 'function' ? options => window.showSaveFilePicker(options) : undefined);
  fallback.onclick = () => perform('original');
  group.append(check, original, fallback, cancel, message); li.append(group);
}
function rustGISItemAction(item) {
  const selves = (Array.isArray(item.links) ? item.links : []).filter(link => link && typeof link === 'object' && link.rel === 'self' && typeof link.href === 'string');
  for (const self of selves) {
    let handoff;
    try {
      const authRefs = Object.prototype.hasOwnProperty.call(self, 'auth:refs') ? self['auth:refs'] : [];
      handoff = rustGISItemHandoff({href: client.linkURL(item, self), type: self.type, authRefs});
    } catch { continue; }
    if (!handoff.available) continue;
    const section = el('section', null, 'rustgis-item');
    const link = addLink(section, 'Open item in RustGIS ↗', handoff.href);
    if (!link) continue;
    link.className = 'rustgis-item-link';
    link.setAttribute('aria-label', `Open STAC Item ${item.id} in RustGIS`);
    section.append(el('small', 'RustGIS chooses the Item’s visual asset or first GeoTIFF. Provider CORS, range, format, size, and access rules still apply.'));
    return section;
  }
  return null;
}
function externalAssetAction(builder, fallback, asset, access, base, roles) {
  const alternates = asset.alternate && typeof asset.alternate === 'object' ? Object.values(asset.alternate) : [];
  const candidates = [...new Set([access, asset, ...alternates].filter(location => location && typeof location === 'object'))];
  let firstFailure = null;
  for (const location of candidates) {
    if (typeof location.href !== 'string') continue;
    const ownsAuth = Object.prototype.hasOwnProperty.call(location, 'auth:refs');
    const primaryOwnsAuth = Object.prototype.hasOwnProperty.call(asset, 'auth:refs');
    const authRefs = ownsAuth ? location['auth:refs'] : location !== asset && primaryOwnsAuth ? asset['auth:refs'] : [];
    const result = builder({href: location.href, base, type: location.type || asset.type, roles, authRefs});
    if (result.available) return result;
    firstFailure ||= result;
  }
  return firstFailure || {available: false, reason: fallback};
}
function rustGISAssetAction(asset, access, base, roles) {
  return externalAssetAction(rustGISAssetHandoff, 'RustGIS needs a public HTTP(S) asset address.', asset, access, base, roles);
}
function geoLibreAssetAction(asset, access, base, roles) {
  return externalAssetAction(geoLibreAssetHandoff, 'GeoLibre needs a public HTTPS asset address.', asset, access, base, roles);
}
function datasetDownloads(item) {
  const section = el('section', null, 'dataset-downloads');
  section.setAttribute('aria-labelledby', 'download-heading');
  const heading = el('h3', 'Download dataset'); heading.id = 'download-heading';
  section.append(heading);
  const assets = el('ul', null, 'download-assets'), base = client.baseFor(item);
  const clipCandidates = [];
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
    // Inspect the source spelling, before safeURL can normalize a hostile path.
    const authURL = isProtectedURL(access.href) ? access.href : null;
    let sessionAsset = Boolean(copernicus);
    try { sessionAsset ||= new URL(safeURL(href)).origin === 'https://download.dataspace.copernicus.eu'; } catch { /* Unsafe links receive no session controls. */ }
    if (sessionAsset) li.dataset.sessionAsset = key;
    if (sessionAsset && !authURL) li.append(el('small', 'Token access is unavailable for this URL: it is outside the permitted Copernicus download scope. Use the official provider browser.', 'scope-unavailable'));
    const accessOwnsAuth = Object.prototype.hasOwnProperty.call(access, 'auth:refs');
    const assetOwnsAuth = Object.prototype.hasOwnProperty.call(asset, 'auth:refs');
    const authDeclaration = accessOwnsAuth ? access['auth:refs'] : assetOwnsAuth ? asset['auth:refs'] : [];
    const authRefs = Array.isArray(authDeclaration) ? authDeclaration : [];
    const invalidAuth = !Array.isArray(authDeclaration);
    const auth = Boolean(copernicus) || invalidAuth || authRefs.length > 0;
    if (auth) {
      if (!copernicus) otherRestrictedAssets = true;
      li.append(el('small', 'Provider authentication required'));
      for (const ref of authRefs) {
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
    if (authURL) protectedControls(li, {href: authURL, asset, key});
    const rustgis = rustGISAssetAction(asset, access, base, roles);
    if (rustgis.available) {
      const link = addLink(li, 'Add to RustGIS ↗', rustgis.href);
      link.className = 'rustgis-add';
      link.setAttribute('aria-label', `Add ${label} to RustGIS`);
      li.append(el('small', 'Opens this exact public asset in RustGIS Web. Its server must allow browser CORS; streamed formats also need Range access.'));
    } else li.append(el('small', rustgis.reason, 'rustgis-unavailable'));
    const geolibreRoles = Object.prototype.hasOwnProperty.call(asset, 'roles') ? asset.roles : roles;
    const geolibre = geoLibreAssetAction(asset, access, base, geolibreRoles);
    if (geolibre.available) {
      const link = addLink(li, 'Check & add to GeoLibre ↗', geoLibreBridgeURL(geolibre, document.baseURI));
      link.className = 'geolibre-add';
      link.setAttribute('aria-label', `Add ${label} to GeoLibre`);
      li.append(el('small', 'Checks browser CORS and Range access after you click. Compatible assets continue to GeoLibre; otherwise you can download and import the file locally or try the remote URL anyway.'));
    } else li.append(el('small', geolibre.reason, 'geolibre-unavailable'));
    const fieldwork = el('button', 'Download FieldWork selection (.json)', 'fieldwork-selection-download'); fieldwork.type = 'button';
    fieldwork.onclick = () => {
      try {
        const handoff = buildFieldworkSelection({item, assetKey: key, accessHref: href, sourceDocument: client.sourceFor(item), itemBase: base,
          catalog: {url: client.url, id: client.root?.id ?? null, title: client.root?.title ?? null}, completedSearch: client.provenance()});
        download(`${item.id}-${key}-fieldwork-selection`.replace(/[^a-zA-Z0-9_.-]/g, '_').slice(0, 150) + '.json', handoff);
      } catch (error) { li.append(el('small', error.message, 'error')); }
    };
    li.append(fieldwork, el('small', 'Metadata handoff only. It makes no asset request; direct FieldWork STAC import is future work.'));
    const clipCandidate = cropOption(li, {item, key, asset, href, supporting, auth, copernicus, authURL});
    if (clipCandidate) clipCandidates.push(clipCandidate);
    assets.append(li);
  }
  section.append(promotedCropWorkflow(clipCandidates));
  queueMicrotask(updateCropBounds);
  section.append(el('p', copernicusDataLinks
    ? copernicusSession.loaded
      ? 'Your token is loaded. Check each supported asset, save its original file, or clip a supported TIFF with the study bbox. Loading does not verify access. Provider download links remain available if an action is unavailable or fails; NetCDF is original-only.'
      : 'Copernicus downloads require sign-in. Open the dataset in the official Copernicus STAC browser, log in, and expand the named asset. Select HTTPS if offered, then Download. Opening the raw API URL alone returns 401 Unauthorized. Files contain the full asset, not a study-area clip.'
    : fileLinks
    ? `${fileLinks === restrictedFileLinks ? 'These data links require provider authentication.' : 'Choose a file below.'} Files open at the provider; if displayed, use your browser’s Save option. Downloads contain the full asset, not a study-area clip.`
    : 'No browser-downloadable data file is advertised. Check the asset instructions and Source links below for provider access.', 'download-help session-download-help'));
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
function highlightSelection(item, button, fit = true) {
  footprints.eachLayer(layer => layer.setStyle({color: '#386a4e', weight: 1.7, fillOpacity: 0}));
  const layer = itemLayers.get(item);
  if (layer) { layer.setStyle({color: '#b56c28', weight: 3, fillOpacity: .12}); layer.bringToFront(); if (fit && layer.getBounds().isValid()) map.fitBounds(layer.getBounds(), {maxZoom: 9, padding: [20, 20]}); }
  document.querySelectorAll('.result-card').forEach(n => n.classList.remove('selected')); button?.classList.add('selected');
}
function select(item, button, fit = true) {
  cancelCrop(); cropSelection++; selectedItem = item;
  highlightSelection(item, button, fit);
  const panel = $('metadata'), rustgis = rustGISItemAction(item);
  panel.replaceChildren(el('h3', item.properties?.title || item.id), datasetDownloads(item), ...(rustgis ? [rustgis] : []));
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
