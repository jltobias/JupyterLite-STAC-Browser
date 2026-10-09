"""Explicitly refresh the public STAC Index snapshot; never run during builds."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unicodedata
from urllib.request import Request, urlopen

SOURCE = "https://stacindex.org/catalogs?access=public"
API = "https://stacindex.org/api/catalogs"
DESTINATION = Path(__file__).resolve().parents[1] / "web/public-catalogs.json"
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 5000
FIELDS = ("id", "slug", "title", "url", "access", "isApi")


def sort_key(row):
    title = "".join(c for c in unicodedata.normalize("NFKD", row["title"]) if not unicodedata.category(c).startswith("M")).lower()
    return title, row["url"], row["id"]


def normalize_catalogs(data):
    """Validate a complete response, retain public rows and advertised URLs verbatim."""
    if not isinstance(data, list) or not 0 < len(data) <= MAX_ROWS:
        raise ValueError("Directory must be a nonempty array of at most 5000 listings.")
    catalogs, ids = [], set()
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get("access"), str):
            raise ValueError("Invalid directory listing/access field.")
        if row["access"] != "public":
            continue
        if (type(row.get("id")) is not int or not 0 < row["id"] <= 9007199254740991
                or type(row.get("isApi")) is not bool
                or any(not isinstance(row.get(key), str) or not row[key].strip() or len(row[key]) > 8192
                       or any(0xD800 <= ord(c) <= 0xDFFF for c in row[key])
                       for key in ("slug", "title", "url"))):
            raise ValueError("Invalid public directory listing fields.")
        if row["id"] in ids:
            raise ValueError("Duplicate public directory listing ID.")
        ids.add(row["id"])
        catalogs.append({key: row[key] for key in FIELDS})
    if not catalogs:
        raise ValueError("Directory contains no public listings.")
    return sorted(catalogs, key=sort_key)


def snapshot(data, fetched_at=None):
    return {"source": SOURCE, "api": API,
            "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "catalogs": normalize_catalogs(data)}


def update(destination=DESTINATION, opener=urlopen):
    request = Request(API, headers={"Accept": "application/json", "User-Agent": "JupyterLite-STAC-Browser directory updater"})
    with opener(request, timeout=20) as response:
        if response.status != 200 or response.url != API:
            raise ValueError("Unexpected directory response status or redirect.")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Directory response exceeds 4 MiB.")
    data = snapshot(json.loads(raw))
    # Validate everything before an atomic replacement; a failed refresh keeps the file.
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, destination)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        data = update()
    except (OSError, ValueError) as error:
        parser.exit(1, f"Directory unchanged: {error}\n")
    print(f"Saved {len(data['catalogs'])} public listings, fetched {data['fetched_at']}, to {DESTINATION}")


if __name__ == "__main__":
    main()
