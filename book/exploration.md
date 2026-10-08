# Explore, inspect, reuse

## Connect to a catalog

WorldPop connects to `https://api.stac.worldpop.org`. Select a collection by its country ISO3 identifier, such as `UGA` or `KEN`. Collection lists load once per connection; providers may return more collections than a requested page limit. The explorer caps its collection list at 1,000 and offers another page only when advertised.

Choose **Copernicus Data Space** (the second option), Earth Search, or Planetary Computer, then **Connect to catalog**, to switch providers. For a custom source, enter an HTTPS STAC Catalog or Collection URL. The client follows advertised `data` and `search` links; it does not guess search endpoints.

Copernicus connects to `https://stac.dataspace.copernicus.eu/v1`, the API behind the [Copernicus STAC browser](https://browser.stac.dataspace.copernicus.eu/). Its collection request asks for up to 1,000 entries so Sentinel collections can be found without stepping through many small pages. Collections appear alphabetically by title (or ID when no title is supplied); use **Load more collections** if another page is offered within the cap. For a first query, choose **Sentinel-2 Level-2A** (`sentinel-2-l2a`), enter `2.2,48.7,2.5,49` as the bounding box around Paris, and use June 1–15, 2024. Set **Per page** to 10, then search. Global collection extents can be large, so refine the area and dates after selecting one. See the [official STAC documentation](https://documentation.dataspace.copernicus.eu/APIs/STAC.html) for provider details.

Static catalogs can be explored through `child` and `item` links. The explorer explains when no remote Item Search is available. It does not recursively fetch an entire static catalog.

## Define a search

Selecting a collection shows its read-only coverage as a dashed blue outline and zooms to it. The purple study area is separate. Until you edit it, its rectangle follows the collection's exact usable extent. Deliberate edits survive later collection changes. **Show study area** returns to your area; **Use collection coverage** resets it to the selected extent and resumes following collections. **All collections**, missing extents, and point/line or date-line extents preserve a usable study area.

Use **Draw rectangle** and click two opposite corners. **Cancel drawing** or Escape keeps the previous area. With **Edit study area** enabled, drag its body to move it or corners to resize it. **Convert to polygon** keeps the current shape and exposes vertices: drag them to reshape, click midpoint handles to insert a vertex, and right-click a vertex to remove it. At least three vertices must remain. For keyboard or touch editing, expand **Edit polygon coordinates**, edit longitude, latitude pairs (one per line), and choose **Apply vertices**. Add or remove lines to add or remove vertices; the ring closes automatically. Invalid input keeps the previous valid area. Coordinate controls pause during drawing and network requests. Turn editing off to select item footprints; a successful search pauses editing automatically.

You can also pan and zoom, then choose **Use map extent**. The bounding-box field tracks the geometry in WGS84 **west, south, east, north** order. Editing that field replaces the shape with a rectangle. Invalid map edits restore the previous valid shape; invalid text remains marked until corrected. Geometry must be a simple, closed, nonzero-area 2D polygon with 3–500 vertices, without holes, crossing or touching edges, or date-line edges. MultiPolygons are not supported. Validation is planar longitude/latitude validation, not geodesic topology repair. Split antimeridian areas into separate searches. A global rectangle remains usable in bbox mode; narrow it before using exact polygon mode.

Choose **Bounding box** (the default) to send the study area's enclosing `bbox`; choose **Exact polygon** to send its GeoJSON `intersects`, including concave boundaries; choose **No spatial filter** to omit both. The latter still applies the selected collection, dates, and page size. Exact polygon mode never silently retries with a bounding box if a provider rejects the query. These filters select intersecting Item footprints; they do not clip or download rasters. All editing and mode changes are local. Only **Search this area** requests search results. Optional dates form an inclusive day interval; a blank endpoint is open-ended.

**From** starts at the selected collection's earliest advertised temporal date, or **January 1, 2000** when no start is available. **Until** starts at today's date in your browser's local time zone. Connecting to a catalog or changing collections resets these defaults; both fields remain editable and can be cleared after loading. For **All collections**, From uses the earliest start once the complete collection list is loaded. If any relevant start is missing, invalid, or open-ended, more collections remain to load, or the list reaches its 1,000-collection limit, From uses January 1, 2000. Loading more collections preserves dates you edited.

WorldPop's `datetime` may describe a product release rather than the population reference year. Inspect `properties.year` and `properties.project` in the original item JSON to identify the population period and product family. Leave dates blank to discover all available releases.

Choose a page size from 10 to 100. Each search returns a page of metadata, and **Load next page** requests one additional advertised page. The client follows GET or POST next links, supports POST body merging, deduplicates by collection and item ID, and stops at 500 unique items.

An empty result is a valid answer. Remove date filters, try another collection, or broaden the area. The geometry describes coverage; it does not tell you the population inside it.

## Inspect before using data

Select an item card or footprint to see identifiers, dates, providers, license, assets, source links, and original JSON. Asset links are direct provider links and may initiate a large download. Public metadata does not guarantee public assets; Planetary Computer asset URLs may need provider signing outside this tool. Dataset terms remain authoritative.

Copernicus metadata discovery works anonymously. Its Sentinel-2 downloads declare provider authentication requirements; consult the [Copernicus STAC documentation](https://documentation.dataspace.copernicus.eu/APIs/STAC.html) for access instructions. The explorer shows a supplied HTTPS alternative when the primary asset uses S3, and labels authentication requirements advertised in the asset metadata. S3-only assets remain available in the original JSON and GeoJSON export for compatible clients. This app does not sign in or attach access tokens to download links.

## Export and reproduce

**GeoJSON** copies the loaded STAC Items, retaining properties and attribution while resolving relative asset/source links to absolute URLs. The client keeps the original metadata intact. **Search JSON** records the STAC root, query, `spatial_mode`, `study_area` geometry snapshot, actual requests, count, and item cap. Editing settings after a search shows a reminder: displayed results and exports continue to describe that completed query. A failed search also preserves this snapshot. Its `retrieved_at` timestamp records the last successful item/page retrieval; exporting again does not change it. Static-item exports have a null query and retain the item GET request for replay. Exports are disabled when nothing is loaded. Each export is a snapshot of the pages you explicitly loaded, not all matching results.

Use the third tutorial to reload the exported query in Python. Metadata can change between requests, so retain both files when documenting an analysis. The notebooks show how to save results and download them from JupyterLite’s file browser.
