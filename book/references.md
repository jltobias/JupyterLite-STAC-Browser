# References and attribution

## Data and standards

- [WorldPop](https://www.worldpop.org/) provides the default population catalog; see the [Global2 announcement](https://www.worldpop.org/blog/worldpop-global2-global-high-resolution-population-estimates-for-2015-2030/) and [STAC API root](https://api.stac.worldpop.org). Consult each collection’s license, providers, and citations. This project does not relicense population data.
- [STAC specification](https://github.com/radiantearth/stac-spec) defines Catalogs, Collections and Items; [STAC API specification](https://github.com/radiantearth/stac-api-spec) defines discovery and Item Search.
- [Earth Search](https://earth-search.aws.element84.com/v1) is operated by [Element 84](https://element84.com/earth-search/).
- [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/) provides the second catalog preset: [STAC API root](https://stac.dataspace.copernicus.eu/v1), [official API documentation](https://documentation.dataspace.copernicus.eu/APIs/STAC.html), and the user-supplied [STAC browser](https://browser.stac.dataspace.copernicus.eu/). Consult each collection and asset's license, providers, citations, and access requirements.
- [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/docs/overview/about/) provides public metadata and documents asset access.
- Basemap © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL. Respect the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/); this app performs no offline tile prefetch.

## Supplied inspiration and workflow references

These projects inform the workflow; their source code is not copied into this repository.

1. Development Seed, [stac-map](https://github.com/developmentseed/stac-map).
2. [PySTAC Client documentation](https://pystac-client.readthedocs.io/en/stable/).
3. [stacmap quickstart](https://stacmap.readthedocs.io/en/latest/tutorials/quickstart.html).
4. Microsoft, [interactive STAC browser notebook](https://nbviewer.org/github/microsoft/PlanetaryComputerExamples/blob/main/tutorials/interactive-browser.ipynb); [original notebook source](https://github.com/microsoft/PlanetaryComputerExamples/blob/main/tutorials/interactive-browser.ipynb).

## Software and artwork

- [Leaflet 1.9.4](https://leafletjs.com/) — BSD-2-Clause; the vendored distribution retains its license.
- [JupyterLite](https://jupyterlite.readthedocs.io/) and [jupyterlite-pyodide-kernel](https://github.com/jupyterlite/pyodide-kernel) — BSD-3-Clause.
- [Pyodide](https://pyodide.org/) — MPL-2.0; included Python packages retain their own licenses.
- [Jupyter Book 2](https://jupyterbook.org/) and [MyST Markdown](https://mystmd.org/) — MIT; site theme dependencies retain their licenses.
- [DM Sans](https://github.com/googlefonts/dm-fonts) and [Space Grotesk](https://github.com/floriankarsten/space-grotesk) — SIL Open Font License 1.1; delivered optionally by Google Fonts, with system fallbacks.
- [Playwright](https://playwright.dev/python/) — Apache-2.0; used for development verification.

The splash SVG and interface artwork are original work created for this repository. Project code, notebooks, prose and original artwork use the MIT license. See the repository’s `THIRD_PARTY_NOTICES.md`, `LICENSE`, and `CITATION.cff` for credit and citation metadata.
