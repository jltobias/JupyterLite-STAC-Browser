"""Small asynchronous STAC metadata client for Pyodide and standard Python.

No packages, accounts, proxy server, or raster downloads are required.
"""
import asyncio
import copy
import json
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit, urlencode

PRESETS = {
    "worldpop": "https://api.stac.worldpop.org",
    "copernicus": "https://stac.dataspace.copernicus.eu/v1",
    "earthsearch": "https://earth-search.aws.element84.com/v1",
    "planetary": "https://planetarycomputer.microsoft.com/api/stac/v1",
}
MAX_ITEMS = 500


def https_url(value, base=""):
    url = urljoin(base, value)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTPS URL without credentials.")
    return url


def validate_bbox(bbox):
    import math
    values = list(bbox)
    if (len(values) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in values)
            or not (-180 <= values[0] < values[2] <= 180 and -90 <= values[1] < values[3] <= 90)):
        raise ValueError("bbox must be west, south, east, north within longitude/latitude bounds; split antimeridian searches.")
    return values


def validate_polygon(geometry):
    """Validate one simple 2D WGS84 ring, with no holes or date-line edges."""
    import math
    coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if (not isinstance(geometry, dict) or geometry.get("type") != "Polygon"
            or not isinstance(coordinates, list) or len(coordinates) != 1
            or not isinstance(coordinates[0], list) or not 4 <= len(coordinates[0]) <= 501):
        raise ValueError("Use one Polygon with 3–500 vertices and one closed ring; holes and MultiPolygons are not supported.")
    ring = coordinates[0]
    if any(not isinstance(p, (list, tuple)) or len(p) != 2
           or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in p)
           or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in ring):
        raise ValueError("Polygon coordinates must be longitude/latitude within ±180°/±90°. Split date-line areas into separate searches.")
    if list(ring[0]) != list(ring[-1]):
        raise ValueError("Polygon ring must be closed.")

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a, b, p):
        return (cross(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
                and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))

    def intersects(a, b, c, d):
        return ((cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0)
                or on_segment(a, b, c) or on_segment(a, b, d) or on_segment(c, d, a) or on_segment(c, d, b))

    count, area = len(ring) - 1, 0
    for i in range(count):
        a, b, c = ring[i], ring[i + 1], ring[(i + 2) % count]
        if list(a) == list(b):
            raise ValueError("Polygon has duplicate neighboring vertices.")
        if abs(a[0] - b[0]) > 180:
            raise ValueError("Polygon crosses the antimeridian. Split date-line areas into separate searches.")
        if cross(a, b, c) == 0 and sum((a[k] - b[k]) * (c[k] - b[k]) for k in (0, 1)) > 0:
            raise ValueError("Polygon edges overlap. Move or remove the overlapping vertex.")
        area += (a[0] - ring[0][0]) * (b[1] - ring[0][1]) - (b[0] - ring[0][0]) * (a[1] - ring[0][1])
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue
            if intersects(a, b, ring[j], ring[j + 1]):
                raise ValueError("Polygon edges cross or touch. Move or remove vertices to make a simple area.")
    if area == 0:
        raise ValueError("Polygon must enclose a nonzero area.")
    return {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}


def date_range(start=None, end=None):
    for value in (start, end):
        if value and (len(value) != 10 or date.fromisoformat(value).isoformat() != value):
            raise ValueError("Use real YYYY-MM-DD calendar dates.")
    if start and end and start > end:
        raise ValueError("Start date must be before or equal to end date.")
    if not start and not end:
        return None
    return f"{start + 'T00:00:00Z' if start else '..'}/{end + 'T23:59:59.999999Z' if end else '..'}"


def next_request(link, previous):
    request = {"url": https_url(link["href"], previous["url"]), "method": link.get("method", "GET").upper()}
    if request["method"] not in ("GET", "POST"):
        raise ValueError("Only GET and POST pagination are supported.")
    if request["method"] == "POST":
        request["body"] = {**(previous.get("body", {}) if link.get("merge") else {}), **link.get("body", {})}
    return request


async def fetch_json(request, timeout=20):
    """Use browser HTTP under Pyodide; a stdlib adapter elsewhere, with TLS intact."""
    headers = {"Accept": "application/geo+json, application/json"}
    body = json.dumps(request["body"]) if "body" in request else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        from pyodide.http import pyfetch
    except ImportError:
        from urllib.request import Request, urlopen
        def fetch():
            req = Request(request["url"], data=body.encode() if body else None, headers=headers, method=request.get("method", "GET"))
            with urlopen(req, timeout=timeout) as response:
                return json.load(response), response.url
        try:
            return await asyncio.wait_for(asyncio.to_thread(fetch), timeout=timeout + 1)
        except Exception as exc:
            raise RuntimeError(f"STAC request failed (network, HTTP, TLS, timeout, or non-JSON): {exc}") from exc
    try:
        response = await asyncio.wait_for(pyfetch(request["url"], method=request.get("method", "GET"), headers=headers,
                                                 **({"body": body} if body is not None else {})), timeout=timeout)
        if not response.ok:
            raise RuntimeError(f"Provider returned HTTP {response.status}. Retry or choose another catalog.")
        return await asyncio.wait_for(response.json(), timeout=timeout), response.url
    except Exception as exc:
        raise RuntimeError(f"Browser STAC request failed: check network, provider CORS, HTTPS, timeout, and JSON URL. {exc}") from exc


def _links(document):
    values = document.get("links") if isinstance(document, dict) else None
    return [link for link in values if isinstance(link, dict) and isinstance(link.get("href"), str)] if isinstance(values, list) else []


def _link(document, relation):
    return next((link for link in _links(document) if link.get("rel") == relation), None)


def _collections(values):
    return list({c["id"]: c for c in values if isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"]}.values())[:1000]


def _valid_item(item):
    return (isinstance(item, dict) and item.get("type") == "Feature"
            and isinstance(item.get("id"), (str, int)) and not isinstance(item["id"], bool))


def _item_key(item):
    return (item.get("collection") if isinstance(item.get("collection"), str) else "", item["id"])


def _http_url(href, base):
    url = urljoin(base, href)
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only HTTP(S) links without credentials are supported.")
    return url


def _item_location(item, source):
    base = source
    link = _link(item, "self")
    if link:
        try:
            base = _http_url(link["href"], source)
        except ValueError:
            pass
    return {"base": base, "source": source}


class STACBrowser:
    def __init__(self, url=PRESETS["worldpop"], fetcher=fetch_json):
        self.endpoint = https_url(url)
        self.fetcher = fetcher
        self._reset()

    def _reset(self):
        self.url = None
        self.root = None
        self.search_link = None
        self.collections = []
        self.items = []
        self.requests = []
        self.query = None
        self.study_area = None
        self.next = None
        self.collection_next = None
        self.retrieved_at = None
        self._item_locations = {}

    async def connect(self, url=None):
        self._reset()
        self.endpoint = https_url(url if url is not None else self.endpoint)
        document, root_url = await self.fetcher({"url": self.endpoint, "method": "GET"})
        if not isinstance(document, dict) or document.get("type") not in ("Catalog", "Collection") or not document.get("stac_version") or not isinstance(document.get("links"), list):
            raise ValueError("Expected a STAC Catalog or Collection JSON document.")
        search_links = [l for l in _links(document) if l.get("rel") == "search" and str(l.get("method", "GET")).upper() in ("GET", "POST")]
        search_link = next((l for l in search_links if str(l.get("method", "GET")).upper() == "GET"), search_links[0] if search_links else None)
        collections = _collections([document] if document["type"] == "Collection" else [])
        collection_next = None
        data = _link(document, "data")
        if data:
            req = {"url": https_url(data["href"], root_url), "method": "GET"}
            # CDSE defaults to 10 collections per page; request our bounded list in one page.
            if req["url"] == PRESETS["copernicus"] + "/collections":
                req["url"] += "?limit=1000"
            page, response_url = await self.fetcher(req)
            if not isinstance(page, dict) or not isinstance(page.get("collections"), list):
                raise ValueError("Advertised collections URL did not return a collections array.")
            collections = _collections(page["collections"])
            link = _link(page, "next")
            collection_next = next_request(link, {**req, "url": response_url}) if link and len(collections) < 1000 else None
        self.root, self.url = document, root_url
        self.search_link, self.collections, self.collection_next = search_link, collections, collection_next
        return self

    async def more_collections(self):
        if not self.collection_next or len(self.collections) >= 1000:
            return self.collections
        req = self.collection_next
        page, url = await self.fetcher(req)
        if not isinstance(page, dict) or not isinstance(page.get("collections"), list):
            raise ValueError("Invalid collections page.")
        collections = _collections(self.collections + page["collections"])
        link = _link(page, "next")
        collection_next = next_request(link, {**req, "url": url}) if link and len(collections) < 1000 else None
        self.collections, self.collection_next = collections, collection_next
        return self.collections

    async def search(self, bbox=None, collection=None, start=None, end=None, limit=25, *, intersects=None, study_area=None):
        if not self.search_link:
            raise ValueError("Static catalog: remote Item Search is not advertised. Use browse_links() and open_link().")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100.")
        if bbox is not None and intersects is not None:
            raise ValueError("Use either bbox or intersects, never both.")
        query = {"limit": limit}
        if bbox is not None:
            query["bbox"] = validate_bbox(bbox)
        if intersects is not None:
            query["intersects"] = validate_polygon(intersects)
        snapshot = copy.deepcopy(study_area)
        if collection:
            query["collections"] = [collection]
        interval = date_range(start, end)
        if interval:
            query["datetime"] = interval
        # Polygon coordinates can exceed GET URL limits; use an advertised POST link.
        search_link = (next((link for link in _links(self.root) if link.get("rel") == "search"
                            and str(link.get("method", "GET")).upper() == "POST"), self.search_link)
                       if intersects is not None else self.search_link)
        req = {"url": https_url(search_link["href"], self.url), "method": search_link.get("method", "GET").upper()}
        parts = urlsplit(req["url"])
        parameters = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                      if key not in ("bbox", "intersects", "collections", "datetime", "limit")]
        if req["method"] == "POST":
            req["body"] = query
        else:
            parameters.extend((key, json.dumps(value, separators=(",", ":")) if key == "intersects"
                               else ",".join(map(str, value)) if isinstance(value, list) else value) for key, value in query.items())
        req["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(parameters), ""))
        await self._page(req, reset=True)
        self.query = query
        self.study_area = snapshot
        return self.items

    async def _page(self, request, reset=False):
        page, url = await self.fetcher(request)
        if not isinstance(page, dict) or page.get("type") != "FeatureCollection" or not isinstance(page.get("features"), list):
            raise ValueError("Search response is not a GeoJSON FeatureCollection.")
        items = {_item_key(i): i for i in ([] if reset else self.items)}
        locations = {} if reset else self._item_locations.copy()
        for item in page["features"]:
            if _valid_item(item):
                key = _item_key(item)
                items[key] = item
                locations[key] = _item_location(item, url)
                if len(items) >= MAX_ITEMS:
                    break
        link = _link(page, "next")
        self.next = next_request(link, {**request, "url": url}) if link and len(items) < MAX_ITEMS else None
        self.items = list(items.values())
        self._item_locations = locations
        self.requests = ([] if reset else self.requests) + [request]
        self.retrieved_at = datetime.now(timezone.utc).isoformat()

    async def more(self):
        """Fetch exactly one advertised next page, to a maximum of 500 unique items."""
        if self.next:
            await self._page(self.next)
        return self.items

    def browse_links(self):
        return [l for l in _links(self.root) if l.get("rel") in ("child", "item", "parent", "root")][:100]

    async def open_link(self, link):
        url = https_url(link["href"], self.url)
        if link.get("rel") != "item":
            return await STACBrowser(url, self.fetcher).connect()
        request = {"url": url, "method": "GET"}
        item, source = await self.fetcher(request)
        if not _valid_item(item) or not item.get("stac_version"):
            raise ValueError("Expected a STAC Item.")
        self.items, self.requests, self.query, self.next = [item], [request], None, None
        self.study_area = None
        self._item_locations = {_item_key(item): _item_location(item, source)}
        self.retrieved_at = datetime.now(timezone.utc).isoformat()
        return item

    def geojson(self):
        """Copy Items with portable absolute hrefs; leave original metadata intact."""
        features = []
        for item in self.items:
            feature = copy.deepcopy(item)
            location = self._item_locations.get(_item_key(item), {"base": self.url, "source": self.url})
            for link in _links(feature):
                try:
                    link["href"] = _http_url(link["href"], location["source"] if link.get("rel") == "self" else location["base"])
                except ValueError:
                    pass
            assets = feature.get("assets")
            for asset in assets.values() if isinstance(assets, dict) else []:
                if isinstance(asset, dict) and isinstance(asset.get("href"), str):
                    try:
                        asset["href"] = _http_url(asset["href"], location["base"])
                    except ValueError:
                        pass
            features.append(feature)
        return {"type": "FeatureCollection", "features": features}

    def provenance(self):
        mode = ("bbox" if "bbox" in self.query else "polygon" if "intersects" in self.query else "none") if self.query is not None else None
        return copy.deepcopy({"stac_root": self.url, "query": self.query, "spatial_mode": mode,
                              "study_area": self.study_area, "requests": self.requests,
                              "retrieved_at": self.retrieved_at, "count": len(self.items), "max_items": MAX_ITEMS})

    def save(self, prefix="stac"):
        if not self.items:
            raise ValueError("No items loaded; perform a search before exporting.")
        from pathlib import Path
        for suffix, document in (("items.geojson", self.geojson()), ("search.json", self.provenance())):
            Path(f"{prefix}-{suffix}").write_text(json.dumps(document, indent=2), encoding="utf-8")


def explorer_url():
    """Resolve sibling explorer under the same deployment subpath."""
    try:
        from js import location
    except ImportError:
        return "../../explorer/"
    from pathlib import Path
    # JupyterLab rewrites relative iframe URLs through its contents service.
    # A worker's href may be blob:, but its origin is the hosting site origin.
    config = json.loads(Path(__file__).with_name("site-config.json").read_text(encoding="utf-8"))
    return str(location.origin) + config["base_path"].rstrip("/") + "/explorer/"
