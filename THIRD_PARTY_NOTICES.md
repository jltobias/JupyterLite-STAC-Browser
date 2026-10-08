# Third-party notices

Original project code, notebooks, text and the original `assets/splash.svg` are MIT-licensed. The splash is a decorative vector illustration, not a population map. No source code was copied from the supplied inspiration projects.

The deployed site bundles **Leaflet 1.9.4** (BSD-2-Clause); see `web/vendor/LICENSE` for the complete license. JupyterLite and jupyterlite-pyodide-kernel use BSD-3-Clause, JupyterLab uses BSD-3-Clause, Pyodide uses MPL-2.0, and Jupyter Book 2/MyST use MIT. Their distributions include notices for constituent packages. Browser-loaded Python and JavaScript dependencies keep their respective licenses. Build and test tools include nbformat (BSD-3-Clause) and Playwright (Apache-2.0).

The site also bundles **Leaflet-Geoman Free 2.20.0** (MIT), from the pinned npm package `@geoman-io/leaflet-geoman-free@2.20.0`. See [its complete license](web/vendor/LICENSE-geoman) and [bundled dependency notices](web/vendor/GEOMAN-DEPENDENCY-LICENSES.txt). This uses public free rectangle drawing, polygon vertex editing, and layer dragging; no Geoman Pro code or features are included.

Optional fonts are **DM Sans** (Colophon Foundry / Google, [source and OFL](https://github.com/googlefonts/dm-fonts)) and **Space Grotesk** (Florian Karsten, [source and OFL](https://github.com/floriankarsten/space-grotesk)), both SIL Open Font License 1.1. Fonts are requested through Google Fonts; system fonts provide a fallback.

Map tiles and underlying map data: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), Open Database License. Tile access is governed by the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/). Attribution appears on the interactive map. This application does not cache or prefetch tiles for offline use.

**WorldPop**, [**Copernicus Data Space Ecosystem**](https://dataspace.copernicus.eu/) ([STAC browser](https://browser.stac.dataspace.copernicus.eu/), [API documentation](https://documentation.dataspace.copernicus.eu/APIs/STAC.html)), **Earth Search / Element 84**, and **Microsoft Planetary Computer** provide external metadata and dataset links. Dataset licensing varies by collection and asset. Preserve the supplied license, provider information, source links and citation requirements. The software MIT license grants no additional dataset rights. Full Item metadata is retained in exported GeoJSON.

Workflow references supplied for this project:

- Development Seed, [stac-map](https://github.com/developmentseed/stac-map).
- [PySTAC Client documentation](https://pystac-client.readthedocs.io/en/stable/).
- [stacmap quickstart](https://stacmap.readthedocs.io/en/latest/tutorials/quickstart.html).
- Microsoft, [interactive-browser notebook](https://nbviewer.org/github/microsoft/PlanetaryComputerExamples/blob/main/tutorials/interactive-browser.ipynb), with [original source](https://github.com/microsoft/PlanetaryComputerExamples/blob/main/tutorials/interactive-browser.ipynb).

Standards: [STAC specification](https://github.com/radiantearth/stac-spec) and [STAC API specification](https://github.com/radiantearth/stac-api-spec). These references inform interoperability; this project does not claim complete STAC conformance or implement every extension.
