# FieldWork handoff

The Explorer and Python helper can save a versioned, file-based handoff for one STAC Item asset. This prepares evidence for FieldWork while keeping metadata discovery separate from raster acquisition. FieldWork does not currently import `fieldwork-stac-selection/1`; there is no upload, browser message, backend, workflow bundle, or `remote-asset-request` connection. Use FieldWork's implemented **Raster input** manually after obtaining the raster through the provider.

## Selection profile

Choose **Download FieldWork selection (.json)** beside an asset, or call `client.save_fieldwork_selection(item, asset_key)` in notebook 03. Creating the file makes no asset request. The profile binds the Item ID, collection, owner-scoped asset key, original href, resolved HTTP(S) identity, response document, declared media type, roles, authentication references and CRS. It also carries the completed search and its CRS84 study area, UTC Item times, an Item footprint or explicit `geometry_is_null`, and sanitized raw STAC evidence.

These spatial values have different meanings and remain separate:

| Field | Meaning |
| --- | --- |
| `study_area_crs84` | User area retained with the completed metadata search |
| `item_footprint` | Provider-declared STAC Item geometry; it may be null |
| `clipping_boundary` | Boundary requested for a later raster crop |
| `acquisition_boundary` | Actual grid-aligned bounds of bytes saved in a crop |

Bearer values, credential fields, URL user information and common signed-URL query parameters are removed recursively. Authentication declarations remain as evidence, and the handoff directs the user to provider access steps. A declaration such as `image/tiff`, a CRS, or a role remains provider metadata; it is not proof of the bytes or format.

A null Item geometry is preserved as null and explicitly refuses spatial-window readiness. A non-null footprint is still only provider metadata; the selection profile does not verify raster coverage or a clipping window.

## Raster sidecar

An ordinary crop is always saved under the Explorer's existing limits. Afterward, the interface checks FieldWork's implemented raster constraints and lists every mismatch. A crop is called **FieldWork-ready** only when it has explicit geographic WGS84 and PixelIsArea GeoKeys, no ModelTransformation, a finite positive-X/negative-Y grid whose derived bounds agree and stay within CRS84, one band, at most 262,144 cells, and at most 5,000,000 bytes.

For a compatible crop, **Download FieldWork raster handoff (.json)** hashes the already-produced GeoTIFF in the browser. It makes no provider request. The `fieldwork-raster-handoff/1` file records the exact SHA-256 and byte count, CRS, grid, clip and acquired bounds, source lineage, and FieldWork Raster input provenance fields: title, provider, landing and download URLs, identifier, citation, license, version, temporal coverage, publication/access dates, units and notes. The saved GeoTIFF remains the file selected in FieldWork's manual Raster input.

Multiband, other-CRS, PixelIsPoint, rotated, oversized-cell-count or oversized-byte outputs keep their normal crop and provenance downloads. They do not receive a compatibility claim or FieldWork sidecar.

## Evidence and boundary

This integration was designed against FieldWork commit [`e3d60e22663c70b7fd8695fbfd3a58e888a37710`](https://github.com/digital-twin-ph/fieldwork/tree/e3d60e22663c70b7fd8695fbfd3a58e888a37710). At that revision, [Raster input 0.3.1](https://github.com/digital-twin-ph/fieldwork/blob/e3d60e22663c70b7fd8695fbfd3a58e888a37710/widgets/releases/raster_input/0.3.1.json) is implemented, and [raster provenance](https://github.com/digital-twin-ph/fieldwork/blob/e3d60e22663c70b7fd8695fbfd3a58e888a37710/src/raster-provenance.ts) defines the descriptive source fields mirrored by the sidecar. FieldWork's [STAC integration note](https://github.com/digital-twin-ph/fieldwork/blob/e3d60e22663c70b7fd8695fbfd3a58e888a37710/docs/experiments/91-stac-browser-integration.md) explicitly says its STAC discovery node and acquisition path are unimplemented. The local profiles do not claim RDF/SHACL conformance or native `fieldwork/workflow/1` or `fieldwork/bundle/1` compatibility.
