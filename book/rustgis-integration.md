# RustGIS handoff

The Explorer can open a discovered public dataset in [RustGIS Web](https://web.rustgis.app/) without downloading it through this site. Select an Item and use one of two actions in the metadata pane:

- **Add to RustGIS** appears beside a compatible public asset. It opens that exact resolved asset through RustGIS Web's documented `data` deep-link parameter.
- **Open item in RustGIS** appears when the Item advertises a safe JSON `self` link. RustGIS reads the STAC Item, draws its footprint, and chooses its visual asset or first GeoTIFF.

Both actions open a new tab with a blank RustGIS project. Creating or displaying the link makes no asset request from the STAC Browser. RustGIS fetches the selected resource after the user follows the link.

## Clipped local GeoTIFF

The Explorer's **Clip study bbox** card is deliberately placed before the full asset list. If more than one source raster qualifies, its selector binds the crop to the exact asset key. **Clip & download GeoTIFF** makes the bounded file; **Clip, download & open RustGIS** performs that same single crop and download, then opens `https://web.rustgis.app/?blank`.

The destination cannot automatically fetch the in-memory crop. RustGIS documents `data=` for a public web address and local GeoTIFF input through its file picker or drag-and-drop. Its `?embed` message contract exchanges project JSON and safe interface commands, not arbitrary binary files. The Explorer therefore tells the user the downloaded filename and asks them to choose **Add Data** in RustGIS or drag the file onto its map. It never serializes a Blob URL, raster bytes, provider token, signed source URL, or protected source address into the destination. If the popup is blocked, the completed crop remains downloaded and a normal link opens the blank RustGIS project.

This boundary preserves the browser-only deployment and avoids a temporary upload server. See RustGIS's [web application and deep-link documentation](https://github.com/opengeos/RustGIS/blob/main/docs/installation.md) and [embed protocol](https://github.com/opengeos/RustGIS/blob/main/apps/rustgis-web/src/embed.rs).

There is a useful future path, but it requires a RustGIS change. The [origin-private file system (OPFS)](https://developer.mozilla.org/en-US/docs/Web/API/File_System_API/Origin_private_file_system) is private to one scheme/host/port, so the Explorer at `jltobias.github.io` cannot place a file directly into `web.rustgis.app` storage. A same-origin deployment could define a shared, namespaced OPFS inbox, but RustGIS would still need to implement and secure that contract. A more portable option is a documented RustGIS import handshake using [`window.postMessage()`](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage) and a transferable `ArrayBuffer`, with exact origin/source checks, a nonce, filename/type/size validation, and an acknowledgement. Until RustGIS publishes such a receiver, explicit file selection or drag-and-drop is the reliable interoperable workflow.

## Eligible assets

The direct asset action covers browser-supported formats that can be identified from the STAC media type or filename, including GeoTIFF/COG, GeoJSON, CSV/TSV, GeoParquet, FlatGeobuf, GeoPackage, KML/KMZ, GPX, PMTiles, LAS/LAZ, Esri ASCII grids, and explicitly identified zipped Shapefiles. Preview, overview and metadata roles are excluded. NetCDF and JPEG 2000 are not sent because RustGIS Web does not directly read them through this path.

The provider must allow the RustGIS origin to fetch the file with browser CORS. Streamed COG, FlatGeobuf and GeoParquet access also depends on browser-visible HTTP Range support. RustGIS Web limits whole-file downloads to 256 MiB. The destination reports access, size, decoding or format failures; the original Explorer selection remains available.

## Authentication boundary

The handoff contains only a public HTTP(S) address. The Explorer withholds it for URL user information, sensitive signed-query parameters, `auth:refs`, and protected Copernicus OData downloads. The optional Copernicus token remains in the Explorer page's memory and is never placed in a RustGIS URL, browser history, storage or exported metadata. Use the existing provider controls for protected data.

The Item action can still open public STAC metadata. RustGIS has its own provider behavior, including automatic signing for supported Microsoft Planetary Computer Items; that does not transfer credentials from this application.

## Integration evidence

This implementation was checked against [`jltobias/JupyterLite-RustGIS@64ee4e32222c07006ab28a634b759d985a002bda`](https://github.com/jltobias/JupyterLite-RustGIS/tree/64ee4e32222c07006ab28a634b759d985a002bda), which demonstrates the `data` handoff, and upstream [`opengeos/RustGIS@d48fa3880d149ebbdb5e485b105b6c82f7519c7e`](https://github.com/opengeos/RustGIS/tree/d48fa3880d149ebbdb5e485b105b6c82f7519c7e), which implements the pinned `data` and `stac` web parameters. The clipped-file boundary was rechecked against the current upstream web-app and embed documentation linked above. No RustGIS source code is copied into this project.
