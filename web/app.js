import {STACClient, PRESETS, safeURL, viewportBBox, localToday, earliestCollectionDate, collectionBBox} from './stac.js';
const $ = id => document.getElementById(id);
const client = new STACClient();
const map = L.map('map', {worldCopyJump: true}).setView([-2, 32], 5);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);
const footprints = L.featureGroup().addTo(map);
let itemLayers = new WeakMap();
let busy = false, connected = false;
let startEdited = false;
function el(tag, text, className) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n; }
function status(text, error = false) { $('status').textContent = text; $('status').className = error ? 'error' : ''; }
function controls() {
  $('start').disabled = $('end').disabled = busy;
  $('connect').disabled = busy;
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
  if (!collection) { status('All collections selected. Current map and search area kept.'); return; }
  const bbox = collectionBBox(collection);
  if (!bbox) { status('This collection has no usable spatial extent. Current map and bounding box kept; set an area manually.', true); return; }
  const [west, south, east, north] = bbox;
  const crossing = east < west;
  const flat = west === east || south === north;
  map.fitBounds([[south, west], [north, crossing ? east + 360 : east]], {padding: [20, 20], maxZoom: 12, animate: false});
  $('bbox').value = bbox.join(',');
  if (!client.searchLink) status('Collection extent applied. Browse child or item links above; remote search is unavailable.');
  else if (crossing) status('Collection extent crosses the antimeridian. Split it into two searches on either side of ±180°.', true);
  else if (flat) status('Collection extent is a point or line. Enlarge the area and select Use map extent before searching.', true);
  else status('Collection extent applied. Select Search this area to load items.');
};
$('start').oninput = () => { startEdited = true; };
async function connect(url) {
  connected = false; client.reset(); renderResults(); collectionOptions(); dateDefaults(); controls();
  $('metadata').replaceChildren(el('p', 'Select a footprint or an item to inspect its metadata.', 'empty'));
  status('Connecting to catalog…'); $('catalog-links').replaceChildren();
  $('catalog-summary').textContent = 'Connecting…';
  try { await client.connect(url); }
  catch (error) { $('catalog-summary').textContent = 'Connection unavailable. Check the URL or try another catalog.'; throw error; }
  connected = true; $('endpoint').value = client.url; collectionOptions(); dateDefaults();
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
$('preset').onchange = () => { const preset = PRESETS[$('preset').value]; if (preset) $('endpoint').value = preset[1]; else { $('endpoint').value = ''; $('endpoint').focus(); } };
$('connect-form').onsubmit = event => { event.preventDefault(); run(() => connect($('endpoint').value)); };
$('use-map').onclick = () => {
  const b = map.getBounds();
  try { $('bbox').value = viewportBBox(b.getWest(), b.getSouth(), b.getEast(), b.getNorth()).map(x => +x.toFixed(5)).join(','); }
  catch (error) { status(error.message, true); return; }
  status('Bounding box updated from the map. Select Search this area to request items.');
};
$('search-form').onsubmit = event => { event.preventDefault(); run(async () => {
  status('Searching metadata…');
  await client.search({bbox: $('bbox').value, collection: $('collection').value, start: $('start').value, end: $('end').value, limit: $('limit').value});
  $('metadata').replaceChildren(el('p', 'Select one of the new results to inspect its metadata.', 'empty'));
  renderResults();
  status(client.items.length ? `${client.items.length} items loaded. Select an item to inspect its assets.${client.next ? ' Another page is available.' : ''}` : 'No items match this area and date range. Try a larger area or remove the date filter.');
}); };
$('more').onclick = () => run(async () => { status('Loading next page…'); await client.more(); renderResults(); status(`${client.items.length} unique items loaded (maximum 500).`); });
$('more-collections').onclick = () => run(async () => { await client.moreCollections(); collectionOptions(); dateDefaults(false); status(`${client.collections.length} collections loaded (maximum 1000).`); });
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
        const layer = L.geoJSON(item, {style: {color: '#386a4e', weight: 1.7, fillColor: '#c0d981', fillOpacity: 0}, pointToLayer: (_, latlng) => L.circleMarker(latlng, {radius: 7, color: '#386a4e', fillOpacity: 0})});
        layer.on('click', () => { select(item, button); button.scrollIntoView({block: 'nearest'}); });
        layer.bindTooltip(el('span', item.properties?.title || item.id)); footprints.addLayer(layer);
        itemLayers.set(item, layer);
      } catch { /* Invalid provider geometry does not hide its metadata. */ }
    }
  }
}
function addLink(parent, text, href, base) {
  try { const a = el('a', text); a.href = safeURL(href, base); a.target = '_blank'; a.rel = 'noopener noreferrer'; parent.append(a); }
  catch { parent.append(el('span', `${text} (unsafe link omitted)`)); }
}
function select(item, button) {
  footprints.eachLayer(layer => layer.setStyle({color: '#386a4e', weight: 1.7, fillOpacity: 0}));
  const layer = itemLayers.get(item);
  if (layer) { layer.setStyle({color: '#b56c28', weight: 3, fillOpacity: .12}); layer.bringToFront(); if (layer.getBounds().isValid()) map.fitBounds(layer.getBounds(), {maxZoom: 9, padding: [20, 20]}); }
  document.querySelectorAll('.result-card').forEach(n => n.classList.remove('selected')); button?.classList.add('selected');
  const panel = $('metadata'); panel.replaceChildren(el('h3', item.properties?.title || item.id));
  const props = item.properties || {};
  panel.append(el('p', props.description || 'No item description supplied.'));
  const collection = client.collections.find(c => c.id === item.collection);
  const providerNames = providers => (Array.isArray(providers) ? providers : []).filter(p => p && typeof p.name === 'string').map(p => p.name).join(', ');
  const providers = providerNames(props.providers) || providerNames(collection?.providers) || 'Not supplied — consult provider';
  const dl = el('dl');
  for (const [key, value] of Object.entries({ID: item.id, Collection: item.collection || 'Not specified', Date: props.datetime || `${props.start_datetime || 'Unknown'} / ${props.end_datetime || 'Unknown'}`, 'Reference year': props.year ?? 'Not specified', Project: props.project || 'Not specified', License: props.license || collection?.license || 'Not supplied — consult provider', Providers: providers})) { dl.append(el('dt', key), el('dd', String(value))); }
  panel.append(dl, el('h3', 'Assets'));
  const assets = el('ul');
  for (const [key, asset] of Object.entries(item.assets || {})) {
    if (!asset || typeof asset !== 'object' || typeof asset.href !== 'string') continue;
    const li = el('li'), base = client.baseFor(item);
    let href = asset.href, label = asset.title || key, access = asset;
    try { safeURL(href, base); }
    catch {
      const alternative = asset.alternate?.https;
      if (typeof alternative?.href === 'string') {
        try { href = safeURL(alternative.href, base, true); label += ' (HTTPS)'; access = alternative; }
        catch { /* Keep unsupported or unsafe URLs non-clickable. */ }
      }
    }
    if (/^s3:/i.test(href)) li.append(el('span', `${label} (S3; use a compatible client)`));
    else addLink(li, label, href, base);
    li.append(el('small', ` · ${asset.type || 'type unspecified'}`));
    if (Array.isArray(access['auth:refs']) && access['auth:refs'].length) li.append(el('small', ' · Provider authentication required'));
    assets.append(li);
  }
  panel.append(assets);
  if (!assets.children.length) panel.append(el('p', 'No assets supplied.'));
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
