# Catalog compatibility audit

**Tested October 13, 2026.** Four of the five featured catalogs completed the live discovery workflow. Digital Earth Africa was unavailable from the browser. Dataset downloads have additional requirements: working metadata access does not guarantee that the provider permits browser range requests, authentication or clipping.

## Featured catalogs

| Catalog | Live discovery | Dataset access checked |
| --- | --- | --- |
| WorldPop | Passed with 248 collections; `UGA` sample | An original 32,157-byte TIFF downloaded successfully through its link. JavaScript range access failed CORS. That sample uses ESRI:54009, which the crop tool does not support. |
| Copernicus Data Space | Passed with 427 collections; `sentinel-2-l2a` sample | Anonymous OData range request returned readable HTTP 401, as expected. Successful downloads and crops with a real user token remain unverified. |
| Digital Earth Africa | Connection unavailable | Browser root access failed CORS/network checks. A separate collections request returned HTTP 200 with an HTML internal-error page instead of STAC JSON. Asset access could not be tested. |
| Earth Search | Passed with 9 collections; `sentinel-2-l2a` sample | Public COG returned HTTP 206 with 16 bytes. A 9 × 13 pixel GeoTIFF crop succeeded; rasterio independently confirmed identical source pixels, CRS and grid alignment. |
| Microsoft Planetary Computer | Passed with 139 collections; `sentinel-2-l2a` sample | Unsigned asset range access failed. This app does not sign assets automatically. A separate public signing probe succeeded, but this environment's browser blocked the signed storage request under its local-address-space network policy. |

For the four successful providers, live UI checks covered alphabetical collections, populated dates, **Until** set to the browser's current date, collection coverage, bounding-box search, pagination, exact-polygon search, no spatial filter, item metadata download, GeoJSON export and Search JSON export. Each initial search returned ten items; the next page produced twenty WorldPop items and twelve for the other three providers. All four polygon and unfiltered searches returned ten items, with no JavaScript page errors.

The selected collection dates were January 1, 2015 for WorldPop and June 27, 2015 for the other three providers. Coverage was Uganda for WorldPop and global for the selected Sentinel-2 collections. WorldPop searches used bbox `29,-2,35,5` without a date filter. Sentinel searches used `2.2,48.7,2.5,49` and June 1–15, 2024. These are representative samples, not an exhaustive test of every collection or asset.

WorldPop's linked original download and its failed CORS read are different browser operations: opening a provider download link can work even when JavaScript cannot read that file. Earth Search's tested server did not expose Content-Range to JavaScript; the 16-byte response and subsequent valid crop provide separate evidence, not an independent verification of the tiny probe's offsets.

Copernicus documents bearer-token authentication for [product downloads](https://documentation.dataspace.copernicus.eu/APIs/OData.html#product-download). The app's memory-only session, header scope, expiry, cancellation, original NetCDF bytes and crop worker are covered by synthetic browser fixtures. Those tests do not establish live authorization with a personal token. See the [official token instructions](https://documentation.dataspace.copernicus.eu/APIs/Token.html).

Planetary Computer documents public metadata and [SAS signing for many Azure assets](https://planetarycomputer.microsoft.com/docs/concepts/sas/). Its public signing API required no account in the probe; a separate server-side signed range request succeeded. The browser's local-network restriction is an environment-specific observation, not evidence that Planetary Computer CORS is broken everywhere. No signed URL or token is included in this report.

Digital Earth Africa's preset still matches its [official direct-access documentation](https://docs.digitalearthafrica.org/en/latest/platform_tools/direct_access.html). The app keeps the provider's failure visible; it does not replace the endpoint or bypass CORS.

## Public directory scope

The audit attempts all **126 listings** in the bundled [STAC Index public directory](https://stacindex.org/catalogs?access=public). A listing can represent an API, a static tree, an old endpoint, or a catalog with collection-level assets. Public listing status does not promise browser compatibility.

Each listing was tested from Chrome at the Explorer's published origin with ordinary TLS and CORS enforcement and no user credentials. API probes requested one item from the first advertised collection. Static probes followed at most four child links, inspected the final reached document, and opened the first advertised Item. The audit limits each metadata response to 8 MiB, uses the client's request timeouts, and runs four independent listing probes concurrently. It does not download directory-listed raster assets or exhaust every branch, collection or page.

The detailed results below distinguish valid empty searches, partial navigation, invalid listing URLs, and failed requests. “Connection failed” can mean a provider/network/CORS failure or an unsupported/non-STAC response; it does not establish that a service is offline. “Static navigation only” means this bounded route found no Item link, not that the catalog has no useful data.

After the client corrections, **61 listings returned a representative Item**, **2 returned valid empty searches**, **20 reached partial static navigation**, and **43 failed connection/navigation or had invalid listed URLs**. Provider availability may change between runs. These totals describe the bounded test, not a certification of each entire catalog.

| Outcome | Listings |
| --- | ---: |
| child search passed | 2 |
| connected; depth cap | 3 |
| connection failed | 39 |
| invalid listed endpoint | 2 |
| navigation/search failed | 2 |
| search passed | 23 |
| static item passed | 38 |
| static navigation only | 17 |

FedEO now returns a valid empty first-collection search through its JSON endpoint. A separate Python search without a collection filter returned one Item. Panoramax returned a response missing the required `FeatureCollection` type; Destination Earth Data Lake returned HTTP 403 during item discovery. The client reports those failures without substituting data.

### Results by listing

| STAC Index listing | Outcome | Detail |
| --- | --- | --- |
| [AerialDataset](https://stacindex.org/catalogs/aerialdataset) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [African Agriculture Adaptation Atlas STAC catalog](https://stacindex.org/catalogs/africa-agriculture-adaptation-atlas) | static item passed | 1 Item(s) |
| [Agroforestry Tree Detection — India (STAC layer)](https://stacindex.org/catalogs/agroforestry-tree-detection-india-stac-layer) | static item passed | 1 Item(s) |
| [Argentina National Geographic Institute (IGN) Reference Layers](https://stacindex.org/catalogs/argentina-ational-geographic-institute) | static navigation only | No Item reached within probe limits |
| [Astraea Earth OnDemand](https://stacindex.org/catalogs/astraea-earth-ondemand) | connection failed | This is not a STAC Catalog or Collection document. |
| [Boettiger Lab Geospatial Datasets](https://stacindex.org/catalogs/boettiger-lab-geospatial-datasets) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [BON in a Box STAC](https://stacindex.org/catalogs/bon-in-a-box-stac) | search passed | 1 Item(s) |
| [California Forest Observatory](https://stacindex.org/catalogs/forest-observatory) | static item passed | 1 Item(s) |
| [Canadian Geospatial Data Collections](https://stacindex.org/catalogs/canadian-geospatial-data-collections-datacube) | search passed | 1 Item(s) |
| [Capella Space Open Data](https://stacindex.org/catalogs/capella-space-open-data) | static item passed | 1 Item(s) |
| [Cassini VIMS-IR STAC catalog](https://stacindex.org/catalogs/cassini-vims-ir) | static item passed | 1 Item(s) |
| [CBERS and Amazonia-1 on AWS](https://stacindex.org/catalogs/cbers) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [CIESIN STAC](https://stacindex.org/catalogs/ciesin-stac) | static navigation only | No Item reached within probe limits |
| [CoCliCo STAC Catalog](https://stacindex.org/catalogs/coclico) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Copernicus Data Space Ecosystem](https://stacindex.org/catalogs/cdse) | search passed | 1 Item(s) |
| [CoRE Stack Spatio Temporal Asset Catalog](https://stacindex.org/catalogs/core-stack-spatio-temporal-asset-catalog) | static item passed | 1 Item(s) |
| [Cubes and Clouds - Snow Cover](https://stacindex.org/catalogs/cubes-and-clouds-snow-cover) | static item passed | 1 Item(s) |
| [Cyverse STAC API](https://stacindex.org/catalogs/cyverse-stac-api) | search passed | 1 Item(s) |
| [data.geo.admin.ch](https://stacindex.org/catalogs/datageoadminch) | search passed | 1 Item(s) |
| [Destination Earth Data Lake (DEDL) API](https://stacindex.org/catalogs/dedl-api) | navigation/search failed | HTTP 403 from provider. Retry later or choose another catalog. |
| [Digital Earth Africa](https://stacindex.org/catalogs/digital-earth-africa) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Digital Earth Australia](https://stacindex.org/catalogs/digital-earth-au) | search passed | 1 Item(s) |
| [Digitale Orthophotos Niedersachsen](https://stacindex.org/catalogs/digitale-orthophotos-niedersachsen) | search passed | 1 Item(s) |
| [Disaster Data Releases from Planet Labs PBC](https://stacindex.org/catalogs/disaster-data-releases-from-planet-labs-pbc) | static item passed | 1 Item(s) |
| [Distributed Renewable Energy (DRE) Atlas](https://stacindex.org/catalogs/dre-atlas) | static item passed | 1 Item(s) |
| [Earth Genome: Sentinel-2 L2A Temporal Mosaics](https://stacindex.org/catalogs/earth-genome) | search passed | 1 Item(s) |
| [Earth Search](https://stacindex.org/catalogs/earth-search) | search passed | 1 Item(s) |
| [EasierData](https://stacindex.org/catalogs/easierdata) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [EcoDataCube.eu](https://stacindex.org/catalogs/eco-datacube) | static item passed | 1 Item(s) |
| [EOC EO Products Service](https://stacindex.org/catalogs/eoc-eo-products-service) | search passed | 1 Item(s) |
| [ERS open data](https://stacindex.org/catalogs/ers-open-data) | connected; depth cap | No Item reached after inspecting four child traversals |
| [ESA Catalog](https://stacindex.org/catalogs/esa-catalog) | connection failed | Request timed out after 20 seconds. Retry or narrow the query. |
| [EuroSAT: Dataset for Land Use and Land Cover Classification](https://stacindex.org/catalogs/eurosat-dataset-for-land-use-and-land-cover) | static item passed | 1 Item(s) |
| [Extremadura SDI (CICTEX)](https://stacindex.org/catalogs/extremadura-sdi-cictex) | static navigation only | No Item reached within probe limits |
| [FAIRiCUBE Hub Catalog](https://stacindex.org/catalogs/fairicube-hub-catalog) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [FedEO Clearinghouse](https://stacindex.org/catalogs/fedeo-clearinghouse) | search passed | 0 Item(s) |
| [fiboa Field Boundaries](https://stacindex.org/catalogs/fiboa) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [FMI ARD Finland](https://stacindex.org/catalogs/fmi-ard-finland) | static item passed | 1 Item(s) |
| [Geoportal des Kantons Bern](https://stacindex.org/catalogs/geoportal-des-kantons-bern) | static item passed | 1 Item(s) |
| [GEP Supersites CSK and CSG data](https://stacindex.org/catalogs/gep-supersites-csk-and-csg-data) | search passed | 1 Item(s) |
| [GHSL Population Grids (GHS-POP R2023A)](https://stacindex.org/catalogs/ghsl-population-grids-ghs-pop-r2023a) | static item passed | 1 Item(s) |
| [GISTDA Drought Index in Thailand](https://stacindex.org/catalogs/gistda-drought-index-in-thailand) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [GISTDA Flood disaster in Thailand](https://stacindex.org/catalogs/gistda-flood-disaster-in-thailand) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Google Earth Engine](https://stacindex.org/catalogs/google-earth-engine) | static navigation only | No Item reached within probe limits |
| [Google Earth Engine (openEO)](https://stacindex.org/catalogs/google-earth-engine-openeo) | static navigation only | No Item reached within probe limits |
| [HDX HAPI Cloud-Native](https://stacindex.org/catalogs/hdx-hapi-cloud-native) | static item passed | 1 Item(s) |
| [Hong Kong CSDI Trial](https://stacindex.org/catalogs/hong-kong-csdi-trial) | static item passed | 1 Item(s) |
| [HUB Ocean´s Ocean Data Platform Catalog](https://stacindex.org/catalogs/hub-oceans-ocean-data-platform-catalog) | search passed | 1 Item(s) |
| [IDE Facultad de Ciencia y Tecnología UADER](https://stacindex.org/catalogs/ide-facultad-de-ciencia-y-tecnologia-uader) | static navigation only | No Item reached within probe limits |
| [Impact Observatory STAC API](https://stacindex.org/catalogs/impact-observatory-stac-api) | search passed | 1 Item(s) |
| [INPE STAC Server](https://stacindex.org/catalogs/inpe-stac-server) | search passed | 1 Item(s) |
| [JRC GloFAS Global Flood Hazard Maps](https://stacindex.org/catalogs/jrc-glofas-global-flood-hazard-maps) | static item passed | 1 Item(s) |
| [KAGIS Katalog](https://stacindex.org/catalogs/kagis-katalog) | connection failed | Request timed out after 20 seconds. Retry or narrow the query. |
| [Kentucky From Above SpatioTemporal Asset Catalog](https://stacindex.org/catalogs/kentucky-from-above-spatiotemporal-asset-catalog) | search passed | 1 Item(s) |
| [LUCAS ML](https://stacindex.org/catalogs/lucas-ml) | static item passed | 1 Item(s) |
| [MapBiomas Annual Land Cover and Land Use, South America](https://stacindex.org/catalogs/mapbiomas-annual-land-cover-and-land-use) | static item passed | 1 Item(s) |
| [Maxar ARD Sample Data](https://stacindex.org/catalogs/maxar-ard-sample-data) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Maxar Open Data Catalog (ARD format)](https://stacindex.org/catalogs/maxar-open-data-catalog-ard-format) | static item passed | 1 Item(s) |
| [Microsoft ML Road Detections](https://stacindex.org/catalogs/microsoft-ml-road-detections) | static navigation only | No Item reached within probe limits |
| [Microsoft Planetary Computer STAC API](https://stacindex.org/catalogs/microsoft-pc) | search passed | 1 Item(s) |
| [MideaFind Germany DIY Store Locations](https://stacindex.org/catalogs/mideafind-germany-diy-store-locations) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [MISTEO STAC SERVER](https://stacindex.org/catalogs/misteo-stac-server) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Monthly Mosaic of Sentinel 2 Images for Catalonia](https://stacindex.org/catalogs/catalonia-monthly-sentinel2) | connection failed | Request timed out after 20 seconds. Retry or narrow the query. |
| [MSC GeoMet - GeoMet-OGC-API](https://stacindex.org/catalogs/msc-geomet) | static navigation only | No Item reached within probe limits |
| [MTD STAC API](https://stacindex.org/catalogs/mtd-stac-api) | search passed | 1 Item(s) |
| [NAIP Aerial Imagery Mosaics](https://stacindex.org/catalogs/naip-aerial-imagery-mosaics) | static item passed | 1 Item(s) |
| [NASA CMR CLOUDSTAC Proxy](https://stacindex.org/catalogs/nasa-cmr-cloudstac-proxy) | child search passed | 1 Item(s) |
| [NASA CMR STAC](https://stacindex.org/catalogs/cmr-stac) | child search passed | 0 Item(s) |
| [NASA ISERV](https://stacindex.org/catalogs/nasa-iserv) | connection failed | This is not a STAC Catalog or Collection document. |
| [National geospatial data of the Republic of Moldova](https://stacindex.org/catalogs/moldova-geodata) | invalid listed endpoint | This listing has no URL scheme. An explicit HTTPS URL is required; the URL has not been changed. |
| [New Zealand Coastal Elevation](https://stacindex.org/catalogs/nz-coastal) | static item passed | 1 Item(s) |
| [New Zealand Elevation](https://stacindex.org/catalogs/nz-elevation) | static item passed | 1 Item(s) |
| [New Zealand Imagery](https://stacindex.org/catalogs/nz-imagery) | static item passed | 1 Item(s) |
| [NOAA Climate Data Records](https://stacindex.org/catalogs/noaa-climate-data-records) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Open Science Catalog](https://stacindex.org/catalogs/osc) | static navigation only | No Item reached within probe limits |
| [OpenAerialMap](https://stacindex.org/catalogs/openaerialmap) | search passed | 1 Item(s) |
| [OpenAerialMap Example](https://stacindex.org/catalogs/openaerialmap-example) | static item passed | 1 Item(s) |
| [OpenLandMap STAC](https://stacindex.org/catalogs/openlandmap) | static item passed | 1 Item(s) |
| [OpenTopography Raster DEM Data Catalog](https://stacindex.org/catalogs/opentopography) | static item passed | 1 Item(s) |
| [Overture Releases](https://stacindex.org/catalogs/overture) | static item passed | 1 Item(s) |
| [Paituli STAC (Finland)](https://stacindex.org/catalogs/paituli-stac-finland) | search passed | 1 Item(s) |
| [Pangeo Cloud Data Catalog](https://stacindex.org/catalogs/pangeo) | connection failed | This is not a STAC Catalog or Collection document. |
| [Panoramax](https://stacindex.org/catalogs/panoramax) | navigation/search failed | Search response is not a GeoJSON FeatureCollection. |
| [Pergamino SDI: Spatial Data Infrastructure](https://stacindex.org/catalogs/pergamino-sdi-spatial-data-infrastructure) | static navigation only | No Item reached within probe limits |
| [PGC Data Catalog](https://stacindex.org/catalogs/pgc-data-catalog) | search passed | 1 Item(s) |
| [Philadelphia Housing and Land Use](https://stacindex.org/catalogs/philadelphia-housing-and-land-use) | static navigation only | No Item reached within probe limits |
| [Planet Labs STAC Catalog](https://stacindex.org/catalogs/planet-labs-stac-catalog) | static item passed | 1 Item(s) |
| [Polar Geospatial Center Data Catalog](https://stacindex.org/catalogs/polar-geospatial-center) | connected; depth cap | No Item reached after inspecting four child traversals |
| [Portolan NL — Cloud-Native Dutch Geodata](https://stacindex.org/catalogs/portolan-nl-cloud-native-dutch-geodata) | static navigation only | No Item reached within probe limits |
| [Portolan Reference Catalog](https://stacindex.org/catalogs/portolan-reference-catalog) | static navigation only | No Item reached within probe limits |
| [PSL / Mines Paris / OIE \| STAC Catalog \| Renewable energy datasets](https://stacindex.org/catalogs/oie-stac-catalog) | connection failed | Use an HTTPS URL without credentials. |
| [RapidAI4EO](https://stacindex.org/catalogs/rapidai4eo-v1) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Rosetta OSIRIS Anaglyphs of Comet 67P](https://stacindex.org/catalogs/rosetta-osiris-anaglyphs) | static item passed | 1 Item(s) |
| [S2 for Ghana](https://stacindex.org/catalogs/s2-for-ghana) | connection failed | This is not a STAC Catalog or Collection document. |
| [Sentinel 3 Level 2+3 on AWS](https://stacindex.org/catalogs/sentinel-3-aws) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Sentinel 5P Level 2 on AWS](https://stacindex.org/catalogs/sentinel-5p-level2-aws) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Sentinel-1 RTC CONUS](https://stacindex.org/catalogs/sentinel-1-rtc-conus) | static item passed | 1 Item(s) |
| [SkyServe Mission Data](https://stacindex.org/catalogs/skyserve-mission-data) | static item passed | 1 Item(s) |
| [Soft Commodity Infrastructure (Brazil)](https://stacindex.org/catalogs/soft-commodity-infrastructure-brazil) | static navigation only | No Item reached within probe limits |
| [South American Rural Cadastral Boundaries](https://stacindex.org/catalogs/south-american-rural-cadastral-boundaries) | static navigation only | No Item reached within probe limits |
| [Space2Stats Database](https://stacindex.org/catalogs/space2stats-database) | connection failed | HTTP 404 from provider. Retry later or choose another catalog. |
| [SPOT Orthoimages of Canada (2005-2010)](https://stacindex.org/catalogs/spot-orthoimages-canada-2005) | connection failed | This is not a STAC Catalog or Collection document. |
| [Super-Resolved Sentinel-2 2.5m STAC API](https://stacindex.org/catalogs/super-resolved-sentinel-2-2-5m-stac-api) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [The Wildland Almanac - California](https://stacindex.org/catalogs/the-wildland-almanac-california) | static item passed | 1 Item(s) |
| [The Wildland Almanac - CONUS](https://stacindex.org/catalogs/the-wildland-almanac-conus) | static item passed | 1 Item(s) |
| [The Wildland Almanac - Treatment Scenarios](https://stacindex.org/catalogs/the-wildland-almanac-treatment-scenarios) | static item passed | 1 Item(s) |
| [Thünen Earth Observation (ThEO)](https://stacindex.org/catalogs/thunen-earth-observation-theo) | search passed | 1 Item(s) |
| [Trazo Field Boundaries of South America](https://stacindex.org/catalogs/trazo-field-boundaries-of-south-america) | static navigation only | No Item reached within probe limits |
| [TriMet Geospatial Data](https://stacindex.org/catalogs/trimet-geospatial-data) | static navigation only | No Item reached within probe limits |
| [UK NCEO Analysis Ready Data (ARD)](https://stacindex.org/catalogs/uk-nceo-analysis-ready-data-ard) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [Umbra Open SAR Data](https://stacindex.org/catalogs/umbra-open-sar-data) | static item passed | 1 Item(s) |
| [United States : NGDA Transportation Theme Data](https://stacindex.org/catalogs/us-ngda-transportation-theme-data) | connection failed | This is not a STAC Catalog or Collection document. |
| [US GeoPlatform](https://stacindex.org/catalogs/geoplatform-stac-catalog) | connected; depth cap | No Item reached after inspecting four child traversals |
| [USGS 3DEP LiDAR Point Clouds](https://stacindex.org/catalogs/usgs-3dep-lidar) | static item passed | 1 Item(s) |
| [USGS Astrogeology Provided Analysis Ready Data](https://stacindex.org/catalogs/usgs-astrogeology-ard) | invalid listed endpoint | This listing advertises HTTP. Browser connections require HTTPS; the URL has not been changed. |
| [USGS Landsat Collection 2 API](https://stacindex.org/catalogs/usgs-landsat-collection-2-api) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [UVT STAC Catalog](https://stacindex.org/catalogs/uvt-stac-catalog) | connection failed | HTTP 500 from provider. Retry later or choose another catalog. |
| [World Bank - Light Every Night](https://stacindex.org/catalogs/world-bank-light-every-night) | connection failed | This is not a STAC Catalog or Collection document. |
| [WorldPop STAC API](https://stacindex.org/catalogs/worldpop-stac-api) | search passed | 1 Item(s) |
| [Wyvern Open Data](https://stacindex.org/catalogs/wyvern-open-data) | static item passed | 1 Item(s) |
| [🇺🇸  United States \| Disasters Community Data](https://stacindex.org/catalogs/us-disasters-community) | connection failed | This is not a STAC Catalog or Collection document. |
| [🇺🇸 United States \| Address Data Theme](https://stacindex.org/catalogs/us-address-data-theme) | connection failed | This is not a STAC Catalog or Collection document. |
| [🇺🇸 United States \| Alabama Geoportal Resources](https://stacindex.org/catalogs/us-al-geoportal-resources) | connection failed | This is not a STAC Catalog or Collection document. |
| [🇺🇸 United States \| Alaska Geospatial Resources](https://stacindex.org/catalogs/us-ak-geospatial-resources) | connection failed | Browser could not reach this URL. Check network, HTTPS certificate, and provider CORS support. A static site cannot bypass CORS. |
| [🇺🇸 United States \| Cadastre Data Theme](https://stacindex.org/catalogs/us-cadastre-data-theme) | connection failed | This is not a STAC Catalog or Collection document. |
| [🇺🇸 United States \| California Geospatial Data](https://stacindex.org/catalogs/us-ca-geospatial-resources) | connection failed | This is not a STAC Catalog or Collection document. |

## Corrections and regression coverage

The audit exposed six groups of application defects, now corrected:

- Choose advertised JSON/GeoJSON search, collection, pagination and static navigation links when HTML or XML representations appear first. FedEO reproduced this live; the corrected JavaScript and Python clients select its GeoJSON endpoint, and Python retrieved an Item.
- Resolve relative alternate asset URLs in exported copies while preserving original metadata.
- Refresh selected metadata, assets and map highlighting when pagination replaces a duplicate Item; cancel an obsolete crop and retain results after a failed page.
- Respect an alternate location's explicit empty authentication declaration instead of inheriting the primary asset's restriction. Copernicus URL recognition still takes precedence.
- Reject spatial searches after invalid applied coordinates or unapplied bbox changes instead of sending the previous geometry.
- Explicitly omit credentials in Python's browser metadata requests.

Deterministic tests also exercise the Earth Search and Planetary Computer dropdown mappings and nested static child/parent/root/Item navigation. These complement live probes, which depend on provider availability.

## Remaining compatibility limits

- Pagination supports GET/POST next links and POST body merging, but does not forward provider-specific headers advertised on those links.
- A standalone Collection that exposes only an API `items` link, without `search` or static `item` links, has no remote item-browsing workflow here.
- Static navigation displays at most 100 links. Later links are not paged into the interface.
- For an asset with a usable primary HTTPS URL, the download pane uses that location; it does not offer a chooser for every advertised alternate.
- Asset CORS, supported raster encodings/CRS, provider authentication and signing still apply. NetCDF is original-download only; browser clipping produces GeoTIFF for supported TIFF inputs.

These limits are recorded rather than treating every directory entry as fully functional. See [architecture](./architecture.md) and [the exploration guide](./exploration.md) for other request and crop limits.

## Repeat the audit

Install the repository's development dependencies and Playwright Chromium, or provide an installed Chrome path:

```sh
python tests/live_catalog_check.py --directory --assets
# With an installed browser:
python tests/live_catalog_check.py --directory --assets --chrome "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

By default this checks the published Explorer. `--site-url` accepts another Explorer URL. `--source` serves this checkout's `web/` files at that origin while leaving provider requests live; the JSON summary identifies this mode explicitly. It does not disable browser security or intercept provider responses. Use this before publication and rerun against the deployed application afterward.

Each invocation saves a separate run under ignored `test-results/live-catalogs/`. Provider URLs are removed from JSON summaries to avoid recording embedded keys or signatures. `--assets` requests only 16-byte ranges and a tiny Earth Search crop; it never deliberately downloads a whole source raster. The command reports provider failures and continues, so a completed process is **not** an assertion that all providers passed. Inspect that run's `audit.json`, `presets.json`, `directory.json` and `assets.json`; omitted optional checks are unverified. Ordinary CI uses fixtures for reproducibility.

### Supplemental download and raster checks

The observations above used **Chrome 155.0.8059.40 on Windows**, at the published Explorer origin. The baseline deployed revision was `563ed599a42188a4b476cfec44173e97fa06e3cc`. Corrected-client runs served local application files at the same origin, with provider requests left live. The [sanitized evidence file](https://github.com/jltobias/JupyterLite-STAC-Browser/blob/main/book/catalog-audit-evidence.json) records source hashes, sample identifiers, dimensions and file hashes without asset URLs or tokens. New audit runs record their own application revision, browser version and mode.

The repeat command covers anonymous range requests and generation of a crop. These additional checks were performed separately:

1. **Original WorldPop download:** select `UGA`, search the WorldPop bbox above with cleared dates, select `UGA_DUG_2030`, and open its `grid_l1` download link. Save the original TIFF. The tested file was 32,157 bytes, 547 × 706 pixels, ESRI:54009. This deliberately follows a file link rather than a JavaScript fetch.
2. **Independent crop comparison:** use the Earth Search sample query above and export its GeoJSON. The tested first Item was `S2B_31UDP_20240613_0_L2A`, asset `red`. With the matching audit crop, run the following using the development environment's rasterio and NumPy. It reads a source window for comparison; it does not load the whole source raster.

```python
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import from_bounds

run = Path("test-results/live-catalogs/REPLACE_WITH_RUN_DIRECTORY")
item = json.loads(Path("earthsearch-items.geojson").read_text())["features"][0]
with rasterio.open(run / "earthsearch-crop.tif") as crop:
    with rasterio.open(item["assets"]["red"]["href"]) as source:
        window = from_bounds(*crop.bounds, transform=source.transform)
        window = window.round_offsets().round_lengths()
        assert crop.crs == source.crs
        assert crop.transform.almost_equals(source.window_transform(window))
        assert np.array_equal(crop.read(), source.read(window=window))
```

3. **Planetary signing diagnostic:** use the selected Item's Azure asset with the official [SAS signing API](https://planetarycomputer.microsoft.com/api/sas/v1/docs), then request bytes 0–15 from the returned URL in the browser with credentials omitted. Inspect the network status and browser console without recording the signed URL. In this environment signing returned 200; the browser reported a local-address-space policy denial. A separate server-side 16-byte range returned 206. This diagnoses the environment and provider access; it is not an integrated app feature or a browser-download success.

Authenticated Copernicus checks were not performed with a real token. A user can repeat **Check access and ranges** on an explicit asset after loading their own short-lived token in the app; that result applies only to the tested asset and session.
