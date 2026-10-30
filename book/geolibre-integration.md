# GeoLibre handoff

The Explorer can open a discovered public asset in [GeoLibre Web](https://web.geolibre.app/) without proxying it through this site. Select an Item, find the intended asset under **Download dataset**, and choose **Check & add to GeoLibre**. Creating and displaying the action makes no request for asset bytes. Your click opens a same-origin compatibility page, which checks browser access before continuing to the exact resolved address through GeoLibre's documented `data` parameter.

## Eligible assets

The action covers the formats documented for GeoLibre's direct remote-data URL:

- GeoJSON and GeoParquet vectors
- vector or raster PMTiles
- Cloud-Optimized GeoTIFF candidates
- LAS, LAZ, and COPC point clouds
- EPT point clouds advertised as `ept.json`

GeoLibre dispatches GeoParquet from `.parquet` or `.geoparquet`, PMTiles from `.pmtiles`, and COG candidates from `.tif`, `.tiff`, or `.cog`; a media type alone is not enough for those formats. An extensionless GeoJSON endpoint must declare a GeoJSON media type. For extensionless LiDAR, the handoff includes GeoLibre's `dataType=lidar` hint. A TIFF/COG filename cannot prove that the bytes are cloud optimized; GeoLibre validates and reports the eventual load result.

Generic ZIP archives, plain `application/json`, FlatGeobuf, NetCDF, JPEG 2000, and unknown formats are not sent through this direct contract. A `.json` asset is accepted only when its media type explicitly declares GeoJSON. GeoLibre can support other formats through separate interactive tools or services, but this button only represents the documented `data` workflow.

## Compatibility check and local fallback

After activation, the bridge issues an HTTPS `GET` for `bytes=0-0` with credentials omitted and cancels the response body as soon as the headers arrive. A COG candidate, GeoParquet, PMTiles, or COPC address must return HTTP 206 before the bridge continues. Whole-file GeoJSON, EPT, LAS, and LAZ may return HTTP 200. The check never downloads the complete asset deliberately and is bounded by a timeout.

If the request is readable from the Explorer origin, and Range is honored where required, the bridge immediately redirects to GeoLibre's exact `data` deep link. This is evidence about the selected address, not a guarantee: origin-specific CORS can treat GeoLibre differently, EPT can reference additional resources with their own policies, and GeoLibre still enforces file-size and format-validity limits. Otherwise the bridge explains that browser CORS, Range, TLS, or network policy prevented verification and offers three choices:

1. Download the exact selected asset with the normal provider link.
2. Open GeoLibre and drag the downloaded file onto the map, or use **Add data** and choose the corresponding raster, vector, or point-cloud file layer.
3. Choose **Try remote URL anyway** when the bridge may be conservative. A provider can permit the `web.geolibre.app` origin while rejecting this Explorer's origin.

A reproduced WorldPop TIFF accepted a normal browser download but returned HTTP 200 to the one-byte Range request and omitted `Access-Control-Allow-Origin`. That response cannot support GeoLibre's browser fetch. Navigation downloads are governed differently from cross-origin JavaScript fetches, so a working Download link does not prove that remote layer loading will work. The bridge does not claim that a filename ending in `.tif` is actually cloud optimized.

GeoLibre downloads plain LAS/LAZ files as a whole and refuses one when the server reports a size above 250 MB; COPC is preferable for large point clouds. Provider behavior remains authoritative after the handoff.

## Credentials stay here

Only a public HTTPS address can be transferred; an HTTP source would be blocked as mixed content after opening the HTTPS GeoLibre application. The Explorer withholds the action for URL user information, sensitive signed or credential query parameters, `auth:refs`, malformed or supporting preview/overview/metadata roles, and the protected Copernicus download origin. The optional Copernicus token remains in this page's memory and is never placed in a GeoLibre URL, browser history, storage, or export. Use the provider controls for protected data.

GeoLibre also documents a `stac` parameter, but it opens a static catalog, STAC API root, or API Collection and begins a new search. It is not used for the selected Item because it would not preserve the exact asset chosen here.

## Evidence and attribution

This implementation was checked against [`jltobias/JupyterLite-GeoLibre-GeoAI@dda3a4667a1267b5ac4858723c46d8c0c82cb7a6`](https://github.com/jltobias/JupyterLite-GeoLibre-GeoAI/tree/dda3a4667a1267b5ac4858723c46d8c0c82cb7a6) and upstream [`opengeos/GeoLibre@b08ed24b60221a3989824cea4678868dfbcc272b`](https://github.com/opengeos/GeoLibre/tree/b08ed24b60221a3989824cea4678868dfbcc272b). The upstream [Embedding & Sharing guide](https://github.com/opengeos/GeoLibre/blob/b08ed24b60221a3989824cea4678868dfbcc272b/docs/user-guide/embedding.md) defines the URL contract and operational limits. No GeoLibre source code is copied into this project.

When publishing results, cite GeoLibre and the original dataset provider. A STAC catalog, this Explorer, and GeoLibre do not replace the asset's license or required attribution.
