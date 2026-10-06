# Explore, inspect, reuse

## Connect to a catalog

WorldPop connects to `https://api.stac.worldpop.org`. Select a collection by its country ISO3 identifier, such as `UGA` or `KEN`. Collection lists load once per connection; providers may return more collections than a requested page limit. The explorer caps its collection list at 1,000 and offers another page only when advertised.

Choose Earth Search or Planetary Computer, then **Connect to catalog**, to switch providers. For a custom source, enter an HTTPS STAC Catalog or Collection URL. The client follows advertised `data` and `search` links; it does not guess search endpoints.

Static catalogs can be explored through `child` and `item` links. The explorer explains when no remote Item Search is available. It does not recursively fetch an entire static catalog.

## Define a search

Pan and zoom to your area, then select **Use map extent**. Bounding boxes use WGS84 longitude and latitude in **west, south, east, north** order. Manual edits are allowed. Split an area that crosses the antimeridian into two searches. Optional dates form an inclusive day interval; a blank endpoint is open-ended.

WorldPop's `datetime` may describe a product release rather than the population reference year. Inspect `properties.year` and `properties.project` in the original item JSON to identify the population period and product family. Leave dates blank to discover all available releases.

Choose a page size from 10 to 100. Each search returns a page of metadata, and **Load next page** requests one additional advertised page. The client follows GET or POST next links, supports POST body merging, deduplicates by collection and item ID, and stops at 500 unique items.

An empty result is a valid answer. Remove date filters, try another collection, or broaden the area. The geometry describes coverage; it does not tell you the population inside it.

## Inspect before using data

Select an item card or footprint to see identifiers, dates, providers, license, assets, source links, and original JSON. Asset links are direct provider links and may initiate a large download. Public metadata does not guarantee public assets; Planetary Computer asset URLs may need provider signing outside this tool. Dataset terms remain authoritative.

## Export and reproduce

**GeoJSON** copies the loaded STAC Items, retaining properties and attribution while resolving relative asset/source links to absolute URLs. The client keeps the original metadata intact. **Search JSON** records the STAC root, query, actual requests, count, and item cap. Its `retrieved_at` timestamp records the last successful item/page retrieval; exporting again does not change it. Static-item exports have a null query and retain the item GET request for replay. Exports are disabled when nothing is loaded. Each export is a snapshot of the pages you explicitly loaded, not all matching results.

Use the third tutorial to reload the exported query in Python. Metadata can change between requests, so retain both files when documenting an analysis. The notebooks show how to save results and download them from JupyterLite’s file browser.
