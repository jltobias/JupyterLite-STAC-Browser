# A world of data. A place to start.

Explore open geospatial catalogs through a map, inspect the metadata behind a footprint, and repeat the search in Python — entirely in your browser.

This field guide joins three views of one workflow: the **Explorer** makes discovery spatial, **JupyterLite** makes queries executable, and these pages explain the choices. Use the navigation above to open either tool. Start with [setup](./setup.md), then follow the [exploration workflow](./exploration.md).

WorldPop is the default source. Its country collections provide entry points to population datasets. Copernicus Data Space is the second catalog option, followed by Digital Earth Africa, Earth Search and Planetary Computer for broader Earth observation discovery. Compatible custom HTTPS STAC catalogs can also be connected. See the dated [catalog compatibility report](./catalog-compatibility.md) for tested workflows and provider access limitations.

```{important}
Map polygons represent **metadata coverage**, not a population raster or population density. No population rasters are downloaded automatically. Catalog metadata, dataset licenses, and provider attribution remain attached to the results.
```

## Your first ten minutes

1. Open **Explorer** and wait for WorldPop collections to load.
2. Choose `UGA`, set an East African bounding box, and search.
3. Select a footprint, refine the study area, and use **Clip study bbox** to make a local GeoTIFF when the raster supports browser ranges.
4. Choose **Clip, download & open RustGIS**, then select or drag the named GeoTIFF into the blank RustGIS project for examination and analysis.
5. Download GeoJSON and Search JSON, then open **Run notebooks** to reproduce the discovery and follow the RustGIS or GeoLibre tutorials.

No account, API key, or application server is needed. Internet access is required for the initial Python runtime download, API requests, and map tiles. This is not an offline GIS or a raster analysis service.
