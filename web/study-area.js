import {bboxValue, collectionBBox, viewportBBox} from './stac.js';
import {polygonValue, geometryBBox, rectangleGeometry} from './geometry.js';

/** Owns the only editable layer. Collection and result metadata never enter it. */
export class StudyArea {
  constructor(map, {status, changed}) {
    this.map = map; this.status = status; this.changed = changed;
    this.input = document.getElementById('bbox');
    this.vertices = document.getElementById('vertices');
    this.mode = document.getElementById('spatial-mode');
    this.edited = false; this.editing = true; this.drawing = false; this.locked = false;
    this.shape = 'rectangle'; this.geometry = null; this.layer = null; this.coverage = null;
    this.collectionExtent = null;
    this.controls = Object.fromEntries(['draw-area', 'cancel-draw', 'edit-area', 'polygon-area', 'zoom-area', 'collection-area', 'use-map', 'apply-vertices'].map(id => [id, document.getElementById(id)]));
    this.setRectangle(bboxValue(this.input.value), false);
    this.input.addEventListener('change', () => {
      try { this.setRectangle(bboxValue(this.input.value)); this.announce('Study rectangle updated.'); }
      catch (error) { this.input.setAttribute('aria-invalid', 'true'); this.status(error.message + ' Previous map area retained.', true); }
    });
    const resumeBoundingBox = () => {
      if (this.mode.value === 'bbox' && !this.editing && !this.drawing && !this.locked) this.setEditing(true);
    };
    // Native selects omit change when the current option is chosen again.
    this.mode.addEventListener('click', resumeBoundingBox);
    this.mode.addEventListener('keyup', event => {
      if (event.key === 'Enter' || event.key === ' ') resumeBoundingBox();
    });
    this.mode.addEventListener('change', () => {
      resumeBoundingBox(); this.updateControls();
      this.announce(this.mode.value === 'none' ? 'No study-area spatial filter: collection and dates still apply.' : this.mode.value === 'polygon' ? 'Exact polygon filtering selected. Providers must support intersects; errors never fall back to bbox.' : 'Bounding-box filtering selected.');
    });
    this.controls['use-map'].onclick = () => this.attempt(() => {
      const b = map.getBounds();
      this.setRectangle(viewportBBox(b.getWest(), b.getSouth(), b.getEast(), b.getNorth()).map(x => +x.toFixed(5)));
      this.announce('Study rectangle updated from the map.');
    });
    this.controls['draw-area'].onclick = () => this.draw();
    this.controls['cancel-draw'].onclick = () => this.cancelDrawing();
    this.controls['edit-area'].onclick = () => this.setEditing(!this.editing);
    this.controls['apply-vertices'].onclick = () => {
      try {
        const ring = this.vertices.value.trim().split(/\r?\n/).filter(line => line.trim()).map(line => line.split(',').map(value => value.trim() ? Number(value) : NaN));
        if (ring.length && (ring[0][0] !== ring.at(-1)[0] || ring[0][1] !== ring.at(-1)[1])) ring.push([...ring[0]]);
        this.replace(polygonValue({type: 'Polygon', coordinates: [ring]}), 'polygon', true);
        this.setEditing(true); this.announce('Polygon vertices applied.');
      } catch (error) {
        this.vertices.setAttribute('aria-invalid', 'true');
        this.status(error.message + ' Previous study area retained.', true);
      }
    };
    this.controls['polygon-area'].onclick = () => this.attempt(() => {
      const geometry = polygonValue(this.geometry);
      this.replace(geometry, 'polygon', true);
      this.setEditing(true); this.announce('Converted to a polygon. Drag vertices, click a midpoint to add, or right-click a vertex to remove it.');
    });
    this.controls['zoom-area'].onclick = () => this.map.fitBounds(this.layer.getBounds(), {padding: [35, 35], maxZoom: 12});
    this.controls['collection-area'].onclick = () => this.attempt(() => {
      this.setRectangle(bboxValue(this.collectionExtent), false); this.edited = false;
      this.announce('Study rectangle reset to collection coverage; it will follow collection changes until edited.');
    });
    map.on('pm:create', event => {
      if (!this.drawing) return;
      const geometry = event.layer.toGeoJSON(false).geometry;
      map.removeLayer(event.layer); this.drawing = false; map.pm.disableDraw();
      try {
        const drawn = geometryBBox(geometry), normalized = viewportBBox(...drawn);
        this.setRectangle(normalized);
        if (drawn[0] !== normalized[0]) this.map.setView(this.map.getCenter().wrap(), this.map.getZoom(), {animate: false});
        this.announce('Study rectangle drawn.');
      }
      catch (error) { this.status(error.message + ' Previous study area retained.', true); }
      this.setEditing(true);
    });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && this.drawing) this.cancelDrawing(); });
    this.updateControls();
  }
  attempt(action) { try { action(); } catch (error) { this.status(error.message, true); } }
  announce(message) { this.status(message + ' Select Search to refresh results.'); this.changed(); }
  setRectangle(bbox, deliberate = true) { this.replace(rectangleGeometry(bbox), 'rectangle', deliberate); }
  replace(geometry, shape, deliberate) {
    if (this.layer) { this.layer.off(); this.layer.pm.disable(); this.layer.pm.disableLayerDrag(); this.map.removeLayer(this.layer); }
    this.geometry = structuredClone(geometry); this.shape = shape;
    if (deliberate) this.edited = true;
    const options = {pane: 'study', color: '#7b3fb2', fillColor: '#9a68c2', weight: 3, fillOpacity: .08, pmIgnore: false, snapIgnore: true, className: 'study-area'};
    const bbox = geometryBBox(geometry);
    this.layer = shape === 'rectangle' ? L.rectangle([[bbox[1], bbox[0]], [bbox[3], bbox[2]]], options) : L.polygon(geometry.coordinates[0].slice(0, -1).map(([lng, lat]) => [lat, lng]), options);
    this.layer.addTo(this.map);
    this.geometry = this.layer.toGeoJSON(false).geometry;
    this.layer.on('pm:edit', () => this.commitEdit());
    this.layer.on('pm:dragend', () => {
      this.commitEdit();
      // Recreate handles at the translated vertices using the public edit API.
      queueMicrotask(() => this.setEditing(this.editing));
    });
    this.syncCoordinates();
    this.setEditing(this.editing);
    this.changed();
  }
  commitEdit() {
    try {
      const geometry = this.layer.toGeoJSON(false).geometry;
      if (this.shape === 'polygon') polygonValue(geometry); else bboxValue(geometryBBox(geometry));
      this.geometry = geometry; this.edited = true;
      this.syncCoordinates();
      this.announce('Study area changed.');
    } catch (error) {
      // Restore only after Geoman's current event handlers finish.
      const previous = structuredClone(this.geometry), shape = this.shape;
      queueMicrotask(() => { this.replace(previous, shape, false); this.status(error.message + ' Previous valid study area restored.', true); });
    }
  }
  setEditing(enabled) {
    this.editing = enabled;
    this.layer.pm.disable(); this.layer.pm.disableLayerDrag();
    if (enabled && !this.drawing && !this.locked) {
      this.layer.pm.enableLayerDrag();
      this.layer.pm.enable({snappable: false, allowSelfIntersection: true, removeLayerBelowMinVertexCount: false, hideMiddleMarkers: this.shape === 'rectangle'});
    }
    this.layer.getElement().style.pointerEvents = enabled && !this.drawing && !this.locked ? 'auto' : 'none';
    this.updateControls();
  }
  draw() {
    this.drawing = true; this.setEditing(false);
    this.map.pm.enableDraw('Rectangle', {snappable: false, continueDrawing: false, pathOptions: {pane: 'study', color: '#7b3fb2', pmIgnore: false}, tooltips: true});
    this.updateControls(); this.status('Click two opposite corners to draw a rectangle. Cancel keeps the previous study area.');
  }
  cancelDrawing() {
    this.map.pm.disableDraw(); this.drawing = false; this.setEditing(true);
    this.status('Drawing canceled. Previous study area retained.');
  }
  setBusy(locked) {
    this.locked = locked; this.input.disabled = this.mode.disabled = locked;
    if (locked && this.drawing) this.cancelDrawing();
    this.setEditing(this.editing);
  }
  syncCoordinates() {
    this.input.value = geometryBBox(this.geometry).join(','); this.input.removeAttribute('aria-invalid');
    this.vertices.value = this.geometry.coordinates[0].slice(0, -1).map(p => p.join(', ')).join('\n');
    this.vertices.removeAttribute('aria-invalid');
  }
  updateControls() {
    if (!this.controls) return;
    for (const button of Object.values(this.controls)) button.disabled = this.locked || this.drawing;
    this.vertices.disabled = this.locked || this.drawing;
    this.controls['cancel-draw'].hidden = !this.drawing;
    this.controls['cancel-draw'].disabled = this.locked;
    this.controls['polygon-area'].disabled ||= this.shape === 'polygon';
    this.controls['collection-area'].disabled ||= !this.collectionExtent || this.collectionExtent[0] >= this.collectionExtent[2] || this.collectionExtent[1] >= this.collectionExtent[3];
    this.controls['edit-area'].setAttribute('aria-pressed', String(this.editing));
    document.getElementById('area-summary').textContent = `${this.shape === 'polygon' ? 'Polygon' : 'Rectangle'} · ${this.drawing ? 'drawing replacement' : this.editing ? 'editing enabled' : 'editing paused; select result footprints'} · ${this.mode.value === 'none' ? 'not used as a spatial filter' : this.mode.value === 'polygon' ? 'exact polygon filter' : 'bounding-box filter'}`;
  }
  showCollection(collection, searchable = true) {
    if (this.drawing) this.cancelDrawing();
    if (this.coverage) { this.map.removeLayer(this.coverage); this.coverage = null; }
    const bbox = collectionBBox(collection); this.collectionExtent = bbox; this.updateControls();
    if (!collection) { this.status('All collections selected. Current map and study area kept.'); return; }
    if (!bbox) { this.status('This collection has no usable spatial extent. Current map and study area kept; set an area manually.', true); return; }
    const [w, s, e, n] = bbox, crossing = e < w, flat = w === e || s === n;
    const bounds = [[s, w], [n, crossing ? e + 360 : e]];
    this.coverage = L.rectangle(bounds, {pane: 'coverage', color: '#597a91', weight: 2, dashArray: '7 5', fillOpacity: 0, interactive: false, pmIgnore: true, snapIgnore: true, className: 'collection-coverage'}).addTo(this.map);
    this.map.fitBounds(bounds, {padding: [20, 20], maxZoom: 12, animate: false});
    if (crossing || flat) {
      this.status(crossing ? 'Collection extent crosses the antimeridian. Study area kept; split date-line areas into separate searches.' : 'Collection extent is a point or line. Study area kept; draw or enter a usable area.', true); return;
    }
    if (!this.edited) this.setRectangle(bbox, false);
    this.status((this.edited ? 'Collection coverage shown. Your edited study area is kept; use Show study area to return to it.' : 'Collection coverage shown; default study rectangle updated.') + (searchable ? ' Select Search to load items.' : ' Browse child or item links; remote search is unavailable.'));
  }
  snapshot() { return {shape: this.shape, geometry: structuredClone(this.geometry), bbox: geometryBBox(this.geometry)}; }
  searchParameters() {
    if (this.drawing) throw new Error('Finish or cancel drawing before searching.');
    if (this.mode.value !== 'none') {
      bboxValue(this.input.value);
      if (!this.geometry) throw new Error('Draw or enter a valid study area before searching.');
    }
    if (this.mode.value === 'polygon') return {intersects: polygonValue(this.geometry), studyArea: this.snapshot()};
    if (this.mode.value === 'bbox') return {bbox: geometryBBox(this.geometry), studyArea: this.snapshot()};
    return {studyArea: this.snapshot()};
  }
}
