# Architecture and troubleshooting

## One static deployment

The site is built into `_site/`: the root is a navigation page, `explorer/` holds plain JavaScript modules and vendored Leaflet and Leaflet-Geoman Free, `lite/` holds JupyterLite and the notebooks, and `book/` holds Jupyter Book 2’s MyST output. GitHub Pages serves only files. No Python web application, private proxy, token, or account is used.

The map client uses browser `fetch`. The Python helper uses `pyodide.http.pyfetch` in Pyodide; outside the browser, a standard-library asynchronous adapter enables deterministic local testing. Both clients follow STAC links and retain source metadata. No GDAL installation or PySTAC Client dependency is required.

Requests are bounded: 20-second network timeouts, 1–100 items per search page, 500 accumulated unique items, 1,000 collections, and at most 100 static navigation links displayed. Pagination is explicit. Dataset assets are links and are never fetched automatically.

`study-area.js` owns one editable layer through the public Geoman Free drawing, layer-dragging, and vertex-editing APIs. Collection coverage and Item footprints occupy separate map panes and are excluded from Geoman. Editing has no search side effects. `geometry.js` and the Python helper validate the same bounded, simple WGS84 polygon shapes; neither repairs topology nor supports holes, MultiPolygons, or date-line edges. A bbox can span the whole world. Search serializes exactly one of `bbox`, `intersects`, or neither; GET encodes `intersects` as JSON and POST sends a geometry object. Exact polygon queries prefer an advertised POST search link; GET-only providers may require fewer vertices if the URL is too long (HTTP 414). There is no silent spatial fallback. Existing unrelated advertised URL parameters remain intact.

Study geometry and spatial mode are captured when a request starts and committed with a successful response. Later UI edits and failed searches keep the previous results, query, requests, and study snapshot together. Notebook 03 replays bbox, exact-polygon, unrestricted, and static-item exports. Geoman 2.20.0 is pinned and served locally under the same deployment subpath, including inside the JupyterLite iframe.

## Public catalog directory

`web/catalog-directory.js` validates, filters and sorts STAC Index listings without probing providers. Its canonical snapshot, `web/public-catalogs.json`, records the official source, API and retrieval date, and retains only id, slug, title, advertised URL, access and API/static type. Only `access == public` records are included. Directory metadata is rendered as text. HTTP, missing-scheme, credential-bearing and unsafe endpoints remain inspectable with an upstream listing link but cannot initiate a connection.

The explicit live refresh uses the existing credential-free browser fetch helper and 20-second timeout. Invalid, non-JSON, unreachable or timed-out responses preserve the previous directory and connection. Filtering and refreshing retain the selected endpoint, even if it disappears from the current results. Relevant controls pause while a provider connection or directory refresh is pending. The directory never crawls providers or fetches every catalog's collections; Connect enters the existing API/static STAC workflow.

Run `python scripts/update_catalog_directory.py` to refresh the bundled file from the official API. The updater caps responses at 4 MiB and 5,000 listings, validates public records, strips unused fields, and replaces the snapshot atomically only on success. Builds copy the canonical file into both Explorer and Lite's browser filesystem, without a live refresh. Relative module/snapshot URLs support source preview, repository subpaths, and the Lite iframe. Notebook 03 filters this same snapshot locally. The canonical `web/public-catalogs.json` records the source and retrieval date; the chooser and notebook display those values and the public listing count. The public directory is supplied by [STAC Index](https://stacindex.org/catalogs?access=public) through its [official API](https://stacindex.org/api/catalogs).

## Common failures

| Symptom | What to do |
| --- | --- |
| Network or CORS error | Check connectivity and HTTPS. A provider must permit the site origin through CORS. Use another preset or contact the provider. There is no client-side bypass. |
| HTTP 429 or 5xx | Wait and retry; reduce the page size. The UI remains available for another connection. |
| Non-JSON response | Use a STAC JSON root rather than a human-facing website. |
| No remote search | Browse static catalog child/item links. Do not assume `/search` exists. |
| No matching items | Broaden bbox/date filters and verify the collection identifier. |
| Invalid bbox | Check axis order and geographic bounds; split antimeridian searches. |
| Invalid polygon | Use one simple closed 2D ring with 3–500 vertices, no holes, no crossing/touching edges, and no date-line edges. |
| Provider rejects exact polygon | Check provider support; choose bbox explicitly if acceptable. The client never falls back silently. |
| Kernel still starting | Wait for Pyodide to download; inspect network restrictions if it stalls. |
| Book assets missing under a repository path | Rebuild with the correct `--base-url`; MyST asset paths are set at build time. |
| Missing basemap | Tile service may be unavailable; metadata search can still succeed. |
| Asset access denied | Consult provider documentation and data terms; this tool does not sign URLs. |

Untrusted metadata is rendered as text. Only HTTP(S) links are shown; API requests require HTTPS and omit credentials. Original metadata remains intact in memory; GeoJSON export copies resolve relative asset/source links using each item's original document base. Provenance records the last successful item/page retrieval time, independently of export time. Large or malformed provider geometry may be omitted from the map while its item card remains available.

## Verification boundaries

Deterministic fixtures cover search, pagination, static navigation, validation, malicious metadata, exports, and error recovery. A separate live smoke check confirms current WorldPop connectivity and a bounded search through real browser CORS. Neither local testing nor a generated site proves a published URL works; verify that URL after a successful deployment.
