# Architecture and troubleshooting

## One static deployment

The site is built into `_site/`: the root is a navigation page, `explorer/` holds plain JavaScript modules and vendored Leaflet, `lite/` holds JupyterLite and the notebooks, and `book/` holds Jupyter Book 2’s MyST output. GitHub Pages serves only files. No Python web application, private proxy, token, or account is used.

The map client uses browser `fetch`. The Python helper uses `pyodide.http.pyfetch` in Pyodide; outside the browser, a standard-library asynchronous adapter enables deterministic local testing. Both clients follow STAC links and retain source metadata. No GDAL installation or PySTAC Client dependency is required.

Requests are bounded: 20-second network timeouts, 1–100 items per search page, 500 accumulated unique items, 1,000 collections, and at most 100 static navigation links displayed. Pagination is explicit. Dataset assets are links and are never fetched automatically.

## Common failures

| Symptom | What to do |
| --- | --- |
| Network or CORS error | Check connectivity and HTTPS. A provider must permit the site origin through CORS. Use another preset or contact the provider. There is no client-side bypass. |
| HTTP 429 or 5xx | Wait and retry; reduce the page size. The UI remains available for another connection. |
| Non-JSON response | Use a STAC JSON root rather than a human-facing website. |
| No remote search | Browse static catalog child/item links. Do not assume `/search` exists. |
| No matching items | Broaden bbox/date filters and verify the collection identifier. |
| Invalid bbox | Check axis order and geographic bounds; split antimeridian searches. |
| Kernel still starting | Wait for Pyodide to download; inspect network restrictions if it stalls. |
| Book assets missing under a repository path | Rebuild with the correct `--base-url`; MyST asset paths are set at build time. |
| Missing basemap | Tile service may be unavailable; metadata search can still succeed. |
| Asset access denied | Consult provider documentation and data terms; this tool does not sign URLs. |

Untrusted metadata is rendered as text. Only HTTP(S) links are shown; API requests require HTTPS and omit credentials. Original metadata remains intact in memory; GeoJSON export copies resolve relative asset/source links using each item's original document base. Provenance records the last successful item/page retrieval time, independently of export time. Large or malformed provider geometry may be omitted from the map while its item card remains available.

## Verification boundaries

Deterministic fixtures cover search, pagination, static navigation, validation, malicious metadata, exports, and error recovery. A separate live smoke check confirms current WorldPop connectivity and a bounded search through real browser CORS. Neither local testing nor a generated site proves a published URL works; verify that URL after a successful deployment.
