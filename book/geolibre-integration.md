# GeoLibre handoff

The Explorer can open a discovered public asset in [GeoLibre Web](https://web.geolibre.app/) without downloading it through this site. Select an Item, find the intended asset under **Download dataset**, and choose **Add to GeoLibre**. A new tab receives the exact resolved address through GeoLibre's documented `data` parameter. Creating and displaying the action makes no request for asset bytes; GeoLibre fetches the resource only after you follow the link.

## Eligible assets

The action covers the formats documented for GeoLibre's direct remote-data URL:

- GeoJSON and GeoParquet vectors
- vector or raster PMTiles
- Cloud-Optimized GeoTIFF candidates
- LAS, LAZ, and COPC point clouds
- EPT point clouds advertised as `ept.json`

GeoLibre dispatches GeoParquet from `.parquet` or `.geoparquet`, PMTiles from `.pmtiles`, and COG candidates from `.tif`, `.tiff`, or `.cog`; a media type alone is not enough for those formats. An extensionless GeoJSON endpoint must declare a GeoJSON media type. For extensionless LiDAR, the handoff includes GeoLibre's `dataType=lidar` hint. A TIFF/COG filename cannot prove that the bytes are cloud optimized; GeoLibre validates and reports the eventual load result.

Generic ZIP archives, plain `application/json`, FlatGeobuf, NetCDF, JPEG 2000, and unknown formats are not sent through this direct contract. A `.json` asset is accepted only when its media type explicitly declares GeoJSON. GeoLibre can support other formats through separate interactive tools or services, but this button only represents the documented `data` workflow.

## Browser and provider requirements

The provider must allow the `web.geolibre.app` browser origin to read the asset through CORS. COG, GeoParquet, PMTiles, and COPC streaming should support HTTP byte-range requests. GeoLibre downloads plain LAS/LAZ files as a whole and refuses one when the server reports a size above 250 MB; COPC is preferable for large point clouds. These are destination/provider behaviors, not guarantees made by the Explorer.

## Credentials stay here

Only a public HTTPS address can be transferred; an HTTP source would be blocked as mixed content after opening the HTTPS GeoLibre application. The Explorer withholds the action for URL user information, sensitive signed or credential query parameters, `auth:refs`, malformed or supporting preview/overview/metadata roles, and the protected Copernicus download origin. The optional Copernicus token remains in this page's memory and is never placed in a GeoLibre URL, browser history, storage, or export. Use the provider controls for protected data.

GeoLibre also documents a `stac` parameter, but it opens a static catalog, STAC API root, or API Collection and begins a new search. It is not used for the selected Item because it would not preserve the exact asset chosen here.

## Evidence and attribution

This implementation was checked against [`jltobias/JupyterLite-GeoLibre-GeoAI@dda3a4667a1267b5ac4858723c46d8c0c82cb7a6`](https://github.com/jltobias/JupyterLite-GeoLibre-GeoAI/tree/dda3a4667a1267b5ac4858723c46d8c0c82cb7a6) and upstream [`opengeos/GeoLibre@4c47d00b5e0b308aed25c2d9a4e69de49e79904e`](https://github.com/opengeos/GeoLibre/tree/4c47d00b5e0b308aed25c2d9a4e69de49e79904e). The upstream [Embedding & Sharing guide](https://github.com/opengeos/GeoLibre/blob/4c47d00b5e0b308aed25c2d9a4e69de49e79904e/docs/user-guide/embedding.md) defines the URL contract and operational limits. No GeoLibre source code is copied into this project.

When publishing results, cite GeoLibre and the original dataset provider. A STAC catalog, this Explorer, and GeoLibre do not replace the asset's license or required attribution.
