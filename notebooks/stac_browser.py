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

    async def search(self, bbox, collection=None, start=None, end=None, limit=25):
        if not self.search_link:
            raise ValueError("Static catalog: remote Item Search is not advertised. Use browse_links() and open_link().")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100.")
        query = {"bbox": validate_bbox(bbox), "limit": limit}
        if collection:
            query["collections"] = [collection]
        interval = date_range(start, end)
        if interval:
            query["datetime"] = interval
        req = {"url": https_url(self.search_link["href"], self.url), "method": self.search_link.get("method", "GET").upper()}
        if req["method"] == "POST":
            req["body"] = query
        else:
            parts = urlsplit(req["url"])
            parameters = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                          if key not in ("bbox", "collections", "datetime", "limit")]
            parameters.extend((key, ",".join(map(str, value)) if isinstance(value, list) else value) for key, value in query.items())
            req["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(parameters), ""))
        await self._page(req, reset=True)
        self.query = query
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
        return {"stac_root": self.url, "query": self.query, "requests": self.requests,
                "retrieved_at": self.retrieved_at, "count": len(self.items), "max_items": MAX_ITEMS}

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
