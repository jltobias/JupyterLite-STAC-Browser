# RustGIS handoff

The Explorer can open a discovered public dataset in [RustGIS Web](https://web.rustgis.app/) without downloading it through this site. Select an Item and use one of two actions in the metadata pane:

- **Add to RustGIS** appears beside a compatible public asset. It opens that exact resolved asset through RustGIS Web's documented `data` deep-link parameter.
- **Open item in RustGIS** appears when the Item advertises a safe JSON `self` link. RustGIS reads the STAC Item, draws its footprint, and chooses its visual asset or first GeoTIFF.

Both actions open a new tab with a blank RustGIS project. Creating or displaying the link makes no asset request from the STAC Browser. RustGIS fetches the selected resource after the user follows the link.

## Eligible assets

The direct asset action covers browser-supported formats that can be identified from the STAC media type or filename, including GeoTIFF/COG, GeoJSON, CSV/TSV, GeoParquet, FlatGeobuf, GeoPackage, KML/KMZ, GPX, PMTiles, LAS/LAZ, Esri ASCII grids, and explicitly identified zipped Shapefiles. Preview, overview and metadata roles are excluded. NetCDF and JPEG 2000 are not sent because RustGIS Web does not directly read them through this path.

The provider must allow the RustGIS origin to fetch the file with browser CORS. Streamed COG, FlatGeobuf and GeoParquet access also depends on browser-visible HTTP Range support. RustGIS Web limits whole-file downloads to 256 MiB. The destination reports access, size, decoding or format failures; the original Explorer selection remains available.

## Authentication boundary

The handoff contains only a public HTTP(S) address. The Explorer withholds it for URL user information, sensitive signed-query parameters, `auth:refs`, and protected Copernicus OData downloads. The optional Copernicus token remains in the Explorer page's memory and is never placed in a RustGIS URL, browser history, storage or exported metadata. Use the existing provider controls for protected data.

The Item action can still open public STAC metadata. RustGIS has its own provider behavior, including automatic signing for supported Microsoft Planetary Computer Items; that does not transfer credentials from this application.

## Integration evidence

This implementation was checked against [`jltobias/JupyterLite-RustGIS@64ee4e32222c07006ab28a634b759d985a002bda`](https://github.com/jltobias/JupyterLite-RustGIS/tree/64ee4e32222c07006ab28a634b759d985a002bda), which demonstrates the `data` handoff, and upstream [`opengeos/RustGIS@d48fa3880d149ebbdb5e485b105b6c82f7519c7e`](https://github.com/opengeos/RustGIS/tree/d48fa3880d149ebbdb5e485b105b6c82f7519c7e), which implements and documents the `data` and `stac` web parameters. No RustGIS source code is copied into this project.
