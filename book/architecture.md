# Architecture and troubleshooting

## One static deployment

The site is built into `_site/`: the root is a navigation page, `explorer/` holds plain JavaScript modules and vendored Leaflet and Leaflet-Geoman Free, `lite/` holds JupyterLite and the notebooks, and `book/` holds Jupyter Book 2’s MyST output. GitHub Pages serves only files. No Python web application, private proxy or shared account is used. Public discovery needs no account; optional protected Copernicus transfers use a personal access token held only in page memory.

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

`web/copernicus-session.js` owns the optional memory-only session and protected transport, separately from the public STAC client. It clears/replaces the input and secret, caps lifetime at ten minutes or decoded JWT expiry, and aborts registered transfers on clear, replacement, expiry or pagehide. Public crop nodes and jobs remain intact when token controls refresh. Unverified claims never establish authentication. No token is put into Items, storage, cookies, requests to public services, exports, crop provenance, URLs or logs. Input controls/oversized values, expired JWTs and recognized refresh/offline JWTs are rejected locally.

The protected transport checks raw URLs before normalization. It permits only the exact HTTPS download origin and recognized OData Products UUID/optional Nodes asset paths ending `$value` or `$zip`, rejecting credentials, query, fragment, path escapes and traversal. It sends Authorization only to that scope, with `credentials: omit`, `cache: no-store` and `redirect: error`. Network/idle waits have a 20-second bound and transfers are bounded by session expiry until save finalization starts. An explicit range check reads exactly 16 bytes with HTTP 206, validating all available headers and rejecting truncated/excess bodies. Exposed Content-Range verifies offsets; hidden headers permit only a status-and-byte-count check, not independent offset verification. Raster transport accepts bounded EOF-shortened 206 reads with the existing public semantics, validating all available headers. Public range behavior is unchanged.

Original-file transfer streams through a user-selected File System Access writable when supported; otherwise it buffers at most 128 MiB and saves a Blob. Known sizes are checked before reads, unknown sizes during reads, and an incomplete/error/canceled transfer requests writable abort. Read/write waits race the transfer abort signal so an idle timeout settles even when a native sink stalls; cleanup does not await an indefinitely stalled abort. Async picker/create/write/fetch boundaries recheck the job before committing or saving. Invoking writable.close() is the final commit boundary after the transfer completes: the UI shows Finishing save and disables Cancel. Token clearing/expiry still discards the secret and obsolete controls, but a file already finalizing cannot be undone and a successful close is reported truthfully. The UI keeps an explicit bounded fallback for exposed but blocked pickers. File bytes are not converted. Authenticated TIFF clipping passes an ephemeral auth snapshot separately from provenance into a fresh worker; each range checks scope and expiry, and session cancellation terminates the worker. No NetCDF clipping or whole-file crop fallback is added.

Session fixtures cover hostile URLs, empty/expired/malformed input, hidden headers, 401/403/network failures, ignored/truncated/oversized ranges, exact original bytes, bounded fallback, actual browser writable-file streaming, real-worker TIFF crops, secret absence from exports/storage and cancellation of pending work. Live anonymous and deliberately invalid-token probes returned readable CORS 401 on October 11, 2026; authorized live access and 206 remain unverified without a real token. See [CDSE token instructions](https://documentation.dataspace.copernicus.eu/APIs/Token.html), [OData downloads](https://documentation.dataspace.copernicus.eu/APIs/OData.html#product-download), [quotas](https://documentation.dataspace.copernicus.eu/Quotas.html#copernicus-general-users), and the [browser writable-file contract](https://developer.mozilla.org/en-US/docs/Web/API/FileSystemFileHandle/createWritable).

Deterministic fixtures cover search, pagination, static navigation, validation, malicious metadata, exports, and error recovery. A separate live smoke check confirms current WorldPop connectivity and a bounded search through real browser CORS. Neither local testing nor a generated site proves a published URL works; verify that URL after a successful deployment.
