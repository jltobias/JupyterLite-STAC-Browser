"""Small asynchronous STAC metadata client for Pyodide and standard Python.

No packages, accounts, proxy server, or raster downloads are required.
"""
import asyncio
import copy
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit, urlencode

PRESETS = {
    "worldpop": "https://api.stac.worldpop.org",
    "copernicus": "https://stac.dataspace.copernicus.eu/v1",
    "deafrica": "https://explorer.digitalearth.africa/stac/",
    "earthsearch": "https://earth-search.aws.element84.com/v1",
    "planetary": "https://planetarycomputer.microsoft.com/api/stac/v1",
}
MAX_ITEMS = 500
SELECTION_PROFILE = "fieldwork-stac-selection/1"
_SECRET_KEY = re.compile(r"(?:^|[_:-])(authorization|bearer|token|access[_-]?token|refresh[_-]?token|password|passwd|secret|signature|sig|credential|api[_-]?key|subscription[_-]?key)(?:$|[_:-])", re.I)
_SENSITIVE_PARAMETER = re.compile(r"^(access_token|refresh_token|id_token|oauth_token|oauth_verifier|token|client_id|client_secret|code|code_verifier|assertion|client_assertion|saml_?response|sig|signature|awsaccesskeyid|googleaccessid|expires|policy|key-pair-id|x-amz-.+|x-goog-.+|se|sp|sr|sv|si|sip|spr|srt|ss|st|ses|skoid|sktid|skt|ske|sks|skv|rscc|rscd|rsce|rscl|rsct|key|api_key|apikey|subscription-key)$", re.I)


def _sanitized_url(value, base=""):
    url = urljoin(base, value)
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("The selected asset has no usable HTTP(S) location.")
    kept, redacted = [], []
    for key, entry in parse_qsl(parsed.query, keep_blank_values=True):
        if _SENSITIVE_PARAMETER.match(key):
            redacted.append(key)
        else:
            kept.append((key, entry))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(kept), "")), sorted(set(redacted))


def _sanitized_reference(value):
    absolute = bool(re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I))
    relative = value.startswith(("./", "../", "/")) or bool(re.match(r"^[^\s?#]+\?[^#]*$", value))
    if not absolute and not relative:
        return value
    try:
        if relative and not value.startswith("//"):
            path, _, query = value.partition("?")
            kept = [(name, entry) for name, entry in parse_qsl(query.split("#", 1)[0], keep_blank_values=True)
                    if not _SENSITIVE_PARAMETER.match(name)]
            return path.split("#", 1)[0] + (("?" + urlencode(kept)) if kept else "")
        parsed = urlsplit(value if absolute else "https:" + value)
        if parsed.username or parsed.password:
            return "[REDACTED UNSAFE URL]"
        kept = [(name, entry) for name, entry in parse_qsl(parsed.query, keep_blank_values=True)
                if not _SENSITIVE_PARAMETER.match(name)]
        sanitized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(kept), ""))
        return sanitized if absolute else sanitized.removeprefix("https:")
    except (TypeError, ValueError):
        return "[REDACTED UNSAFE URL]"


def _sanitize_export(value, key=""):
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        if re.search(r"\bbearer\s+[A-Za-z0-9._~+/=-]+", value, re.I):
            return "[REDACTED]"
        if (re.match(r"^(?:[a-z][a-z0-9+.-]*://|\.?\.?/|/)", value, re.I)
                or re.match(r"^[^\s?#]+\?[^#]*$", value)):
            return _sanitized_reference(value)
        return value
    if isinstance(value, list):
        return [_sanitize_export(entry) for entry in value]
    if isinstance(value, dict):
        return {name: _sanitize_export(entry, name) for name, entry in value.items()}
    return value


def _utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


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
        response = await asyncio.wait_for(pyfetch(request["url"], method=request.get("method", "GET"), headers=headers, credentials="omit",
                                                 **({"body": body} if body is not None else {})), timeout=timeout)
        if not response.ok:
            raise RuntimeError(f"Provider returned HTTP {response.status}. Retry or choose another catalog.")
        return await asyncio.wait_for(response.json(), timeout=timeout), response.url
    except Exception as exc:
        raise RuntimeError(f"Browser STAC request failed: check network, provider CORS, HTTPS, timeout, and JSON URL. {exc}") from exc


def _links(document):
    values = document.get("links") if isinstance(document, dict) else None
    return [link for link in values if isinstance(link, dict) and isinstance(link.get("href"), str)] if isinstance(values, list) else []


def _link(document, relation, json_only=False):
    return next((link for link in _links(document) if link.get("rel") == relation and (not json_only or _json_link(link))), None)


def _json_link(link):
    media_type = link.get("type")
    if media_type is None or media_type == "":
        return True
    if not isinstance(media_type, str):
        return False
    media_type = media_type.split(";", 1)[0].strip().lower()
    return re.fullmatch(r"application/(?:[^\s/;]+\+)?json", media_type) is not None


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
        search_links = [l for l in _links(document) if l.get("rel") == "search" and _json_link(l) and str(l.get("method", "GET")).upper() in ("GET", "POST")]
        search_link = next((l for l in search_links if str(l.get("method", "GET")).upper() == "GET"), search_links[0] if search_links else None)
        collections = _collections([document] if document["type"] == "Collection" else [])
        collection_next = None
        data = next((link for link in _links(document) if link.get("rel") == "data" and _json_link(link)), None)
        if data:
            req = {"url": https_url(data["href"], root_url), "method": "GET"}
            # CDSE defaults to 10 collections per page; request our bounded list in one page.
            if req["url"] == PRESETS["copernicus"] + "/collections":
                req["url"] += "?limit=1000"
            page, response_url = await self.fetcher(req)
            if not isinstance(page, dict) or not isinstance(page.get("collections"), list):
                raise ValueError("Advertised collections URL did not return a collections array.")
            collections = _collections(page["collections"])
            link = _link(page, "next", json_only=True)
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
        link = _link(page, "next", json_only=True)
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
        search_link = (next((link for link in _links(self.root) if link.get("rel") == "search" and _json_link(link)
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
        link = _link(page, "next", json_only=True)
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
        return [l for l in _links(self.root) if _json_link(l) and l.get("rel") in ("child", "item", "parent", "root")][:100]

    async def open_link(self, link):
        if not _json_link(link):
            raise ValueError("The catalog link does not advertise a JSON representation.")
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
                if not isinstance(asset, dict):
                    continue
                alternates = asset.get("alternate")
                locations = [asset, *(alternates.values() if isinstance(alternates, dict) else [])]
                for asset_location in locations:
                    if (not isinstance(asset_location, dict) or not isinstance(asset_location.get("href"), str)
                            or not asset_location["href"].strip()):
                        continue
                    try:
                        asset_location["href"] = _http_url(asset_location["href"], location["base"])
                    except ValueError:
                        pass
            features.append(feature)
        return {"type": "FeatureCollection", "features": features}

    def provenance(self):
        mode = ("bbox" if "bbox" in self.query else "polygon" if "intersects" in self.query else "none") if self.query is not None else None
        return copy.deepcopy({"stac_root": self.url, "query": self.query, "spatial_mode": mode,
                              "study_area": self.study_area, "requests": self.requests,
                              "retrieved_at": self.retrieved_at, "count": len(self.items), "max_items": MAX_ITEMS})

    def fieldwork_selection(self, item, asset_key):
        """Build a secret-free, one-asset metadata handoff without fetching asset bytes."""
        if item not in self.items or not isinstance(item.get("assets"), dict) or asset_key not in item["assets"]:
            raise ValueError("Choose an asset owned by a loaded STAC Item.")
        asset = item["assets"][asset_key]
        if not isinstance(asset, dict) or not isinstance(asset.get("href"), str) or not asset["href"].strip():
            raise ValueError("The selected asset has no usable HTTP(S) location.")
        location = self._item_locations.get(_item_key(item))
        if not location or not location.get("source"):
            raise ValueError("A source-document base is required for a relative asset href.")
        candidates = [asset["href"]]
        alternate = asset.get("alternate")
        if isinstance(alternate, dict):
            candidates.extend(entry.get("href") for entry in alternate.values() if isinstance(entry, dict))
        resolved = redacted_parameters = None
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            try:
                resolved, redacted_parameters = _sanitized_url(candidate, location["base"])
                break
            except ValueError:
                continue
        if resolved is None:
            raise ValueError("The selected asset has no usable HTTP(S) location.")
        original = _sanitized_reference(asset["href"])
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        locations = [asset, *(asset.get("alternate", {}).values() if isinstance(asset.get("alternate"), dict) else [])]
        auth_refs = list(dict.fromkeys(value for entry in locations if isinstance(entry, dict)
                                       for value in (entry.get("auth:refs", []) if isinstance(entry.get("auth:refs"), list) else [])
                                       if isinstance(value, str)))
        provenance = self.provenance()
        study_area = provenance.get("study_area")
        source, source_redacted = _sanitized_url(location["source"])
        source_base, base_redacted = _sanitized_url(location["base"])
        raw_catalog = {"url": self.url, "id": self.root.get("id") if self.root else None,
                       "title": self.root.get("title") if self.root else None}
        sanitized_asset, sanitized_item, sanitized_auth_refs = _sanitize_export(asset), _sanitize_export(item), _sanitize_export(auth_refs)
        sanitized_catalog, sanitized_provenance, sanitized_study_area = (_sanitize_export(raw_catalog),
                                                                          _sanitize_export(provenance), _sanitize_export(study_area))
        credentials_omitted = bool(auth_refs or redacted_parameters or source_redacted or base_redacted or original != asset["href"]
                                   or sanitized_item != item or sanitized_catalog != raw_catalog
                                   or sanitized_provenance != provenance or sanitized_study_area != study_area
                                   or sanitized_auth_refs != auth_refs)
        return {
            "profile": SELECTION_PROFILE,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "discovery": {"catalog": sanitized_catalog,
                          "completed_search": sanitized_provenance, "study_area_crs84": sanitized_study_area},
            "selection": {"collection_id": item.get("collection"), "item_id": str(item.get("id")), "asset_key": asset_key,
                          "source_document": {"response_url": source, "base_url": source_base,
                                              "redacted_query_parameters": sorted(set(source_redacted + base_redacted))},
                          "original_href": _sanitize_export(original),
                          "resolved_http_href": resolved, "redacted_query_parameters": redacted_parameters,
                          "declared": {"media_type": asset.get("type"),
                                       "roles": [value for value in asset.get("roles", []) if isinstance(value, str)] if isinstance(asset.get("roles"), list) else [],
                                       "auth_refs": sanitized_auth_refs,
                                       "crs": asset.get("proj:epsg", asset.get("proj:code", properties.get("proj:epsg", properties.get("proj:code"))))},
                          "access": {"transient_credentials_omitted": credentials_omitted,
                                     "instruction": "Obtain access through the provider, then use FieldWork's manual Raster input."
                                     if credentials_omitted else "Use FieldWork's manual Raster input; direct STAC import is not currently supported."}},
            "spatial": {"item_footprint": _sanitize_export(item.get("geometry")), "geometry_is_null": item.get("geometry") is None,
                        "spatial_window_readiness": ({"verified": False, "ready": False,
                                                       "reason": "Item geometry is null; no footprint or spatial-window readiness is inferred."}
                                                      if item.get("geometry") is None else
                                                      {"verified": False, "ready": None,
                                                       "reason": "Selection metadata does not verify raster coverage or a clipping window."}),
                        "study_area_crs84": _sanitize_export(study_area), "clipping_boundary": None, "acquisition_boundary": None},
            "temporal": {"item_datetime_utc": _utc(properties.get("datetime")), "item_start_datetime_utc": _utc(properties.get("start_datetime")),
                         "item_end_datetime_utc": _utc(properties.get("end_datetime")), "discovered_at_utc": _utc(self.retrieved_at)},
            "evidence": {"raw_stac_item": sanitized_item, "raw_stac_asset": sanitized_asset},
            "compatibility": {"native_fieldwork_import": False, "manual_raster_input": True},
        }

    def save_fieldwork_selection(self, item, asset_key, path=None):
        """Save one versioned selection handoff; this performs no asset request."""
        document = self.fieldwork_selection(item, asset_key)
        if path is None:
            stem = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{item['id']}-{asset_key}-fieldwork-selection")[:150]
            target = Path(stem + ".json")
        else:
            target = Path(path)
        target.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return target

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
