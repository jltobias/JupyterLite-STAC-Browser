"""Optional live compatibility audit; provider failures are reported, not mocked.

Use --directory for every bundled STAC Index listing and --assets for small,
anonymous range probes plus a tiny Earth Search crop. No tokens or full raster
downloads are used. Each invocation creates a new timestamped directory under
test-results/live-catalogs by default, including incomplete runs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urljoin, urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://jltobias.github.io/JupyterLite-STAC-Browser/explorer/"
CASES = [
    ("worldpop", "UGA", "29,-2,35,5", "", ""),
    ("copernicus", "sentinel-2-l2a", "2.2,48.7,2.5,49", "2024-06-01", "2024-06-15"),
    ("deafrica", "s2_l2a", "45,-20.1,47,-19.8", "2020-01-01", "2020-01-31"),
    ("earthsearch", "sentinel-2-l2a", "2.2,48.7,2.5,49", "2024-06-01", "2024-06-15"),
    ("planetary", "sentinel-2-l2a", "2.2,48.7,2.5,49", "2024-06-01", "2024-06-15"),
]


def redact(value):
    """Do not persist provider URLs, which can contain public keys or signatures."""
    if isinstance(value, str):
        value = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+", "[provider URL]", value)
        return re.sub(r"(?i)(?:bearer\s+|(?:access_token|token|sig|signature)=)[^\s&]+", "[redacted credential]", value)
    if isinstance(value, list):
        return [redact(x) for x in value]
    if isinstance(value, dict):
        return {k: '[redacted credential]' if k.lower() in ('authorization', 'cookie', 'token', 'access_token', 'signature', 'sig') else redact(v) for k, v in value.items()}
    return value


def write_json(path, value):
    path.write_text(json.dumps(redact(value), indent=2, ensure_ascii=False), encoding="utf-8")


def source_route(route, site, web_root=ROOT / 'web'):
    relative = unquote(urlsplit(route.request.url).path[len(urlsplit(site).path):]) or 'index.html'
    target = (web_root / relative).resolve()
    if target.is_relative_to(web_root.resolve()) and target.is_file():
        route.fulfill(path=target)
    else:
        route.fulfill(status=404, body='Local source file not found.', content_type='text/plain')


def run_manifest(output, source, enabled, root=ROOT):
    started = datetime.now(timezone.utc)
    out = output / (started.strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid4().hex[:8])
    out.mkdir(parents=True)
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    try:
        revision, dirty = git('rev-parse', 'HEAD'), bool(git('status', '--porcelain'))
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, None
    sources = sorted((root / 'web').rglob('*')) + [root / 'notebooks/stac_browser.py', root / 'tests/live_catalog_check.py']
    summary = {'started_utc': started.isoformat(), 'status': 'incomplete', 'phase': 'browser startup',
               'mode': 'source' if source else 'deployed', 'browser_version': None,
               'enabled_checks': enabled, 'omitted_checks': [x for x in ['presets', 'directory_ui', 'assets', 'directory'] if x not in enabled],
               'git_revision': revision, 'git_dirty': dirty, 'credentials': 'none',
               'hash_scope': 'local workspace source files; deployed bytes are not fingerprinted',
               'source_sha256': {str(path.relative_to(root)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources if path.is_file()}}
    write_json(out / 'audit.json', summary)
    return out, summary


def normalized_bbox(value, usable=False):
    if (not isinstance(value, list) or len(value) not in (4, 6)
            or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value)):
        return None
    dims = len(value) // 2
    if dims == 3 and value[2] > value[5]:
        return None
    w, s, e, n = value[0], value[1], value[dims], value[dims + 1]
    if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= n <= 90):
        return None
    if usable and (w >= e or s >= n):
        return None
    return [w, s, e, n]


def collection_expectations(collection):
    extent = collection.get('extent') if isinstance(collection, dict) else None
    extent = extent if isinstance(extent, dict) else {}
    temporal, spatial = extent.get('temporal'), extent.get('spatial')
    intervals = temporal.get('interval') if isinstance(temporal, dict) else None
    dates = []
    try:
        if not isinstance(intervals, list) or not intervals:
            raise ValueError('missing intervals')
        for interval in intervals:
            start = interval[0] if isinstance(interval, list) and interval else None
            if not isinstance(start, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})', start):
                raise ValueError('missing or invalid start')
            dates.append(datetime.fromisoformat(start.upper().replace('Z', '+00:00')).astimezone(timezone.utc).date().isoformat())
    except (ValueError, OverflowError):
        dates = []
    boxes = spatial.get('bbox') if isinstance(spatial, dict) else None
    bbox = normalized_bbox(boxes[0]) if isinstance(boxes, list) and boxes else None
    state = ('absent or invalid' if bbox is None else 'crossing antimeridian' if bbox[0] > bbox[2]
             else 'point or line' if bbox[0] == bbox[2] or bbox[1] == bbox[3] else 'usable')
    return {'from': min(dates) if dates else '2000-01-01', 'bbox': bbox, 'extent': state}


def asset_address(asset):
    """Use an already portable exported asset with the pane's primary/HTTPS order."""
    if not isinstance(asset, dict):
        return None
    def allowed(href, https_only=False):
        if not isinstance(href, str) or not href.strip():
            return False
        try:
            parts = urlsplit(href)
            return (parts.scheme in (('https',) if https_only else ('http', 'https'))
                    and bool(parts.hostname) and parts.username is None and parts.password is None)
        except ValueError:
            return False
    if allowed(asset.get('href')):
        return asset['href']
    alternatives = asset.get('alternate')
    alternatives = alternatives if isinstance(alternatives, dict) else {}
    for entry in [alternatives.get('https'), *alternatives.values()]:
        if isinstance(entry, dict) and allowed(entry.get('href'), https_only=True):
            return entry['href']
    return None


def tiny_crop_bbox(item):
    bounds = normalized_bbox(item.get('bbox'), usable=True)
    if bounds is None:
        return None
    w, s, e, n = bounds
    x, y = (w + e) / 2, (s + n) / 2
    return [max(w, x-.0005), max(s, y-.0005), min(e, x+.0005), min(n, y+.0005)]


def expected_next(page, previous):
    """Build the advertised request independently from the completed history."""
    links = page['data'].get('links', [])
    for link in links if isinstance(links, list) else []:
        if not isinstance(link, dict) or link.get('rel') != 'next' or not isinstance(link.get('href'), str):
            continue
        media = link.get('type')
        if media not in (None, '') and (not isinstance(media, str) or not re.fullmatch(r'application/(?:[^\s/;]+\+)?json', media.split(';')[0].strip().lower())):
            continue
        method = str(link.get('method') or 'GET').upper()
        request = {'url': urljoin(page['url'], link['href']), 'method': method}
        if method == 'POST':
            request['body'] = {**(previous.get('body', {}) if link.get('merge') else {}), **(link.get('body') or {})}
        return request
    return None


def pagination_matches(before, after, advertised):
    history = before.get('requests', [])
    return bool(advertised and advertised not in history and after.get('requests') == [*history, advertised]
                and after.get('count', -1) >= before.get('count', 0))


def spatial_query_matches(exported, mode, polygon=None):
    query = exported.get('query')
    if not isinstance(query, dict) or exported.get('spatial_mode') != mode:
        return False
    return ('bbox' not in query and query.get('intersects') == polygon if mode == 'polygon'
            else 'bbox' not in query and 'intersects' not in query)


STATIC_PROBE_JS = """async function probeStatic(client, rec) {
    const visited=new Set([client.url]);rec.child_traversal_limit=4;
    for(let depth=0;depth<=4;depth++) {
        rec.traversal_depth=depth;
        const links=client.catalogLinks(), item=links.find(l=>l.rel==='item');
        if(item) {await client.openItem(item);rec.item_count=1;rec.outcome='static item passed';return;}
        const child=links.find(l=>l.rel==='child');
        if(!child) {rec.outcome='static navigation only';return;}
        if(depth===4) {rec.outcome='connected; depth cap';return;}
        const url=new URL(child.href,client.url).href;
        if(visited.has(url)) {rec.outcome='static cycle';return;}
        visited.add(url);await client.connect(url);
        if(client.searchLink) {
            await client.search({collection:client.collections[0]?.id,limit:1});
            rec.traversal_depth=depth+1;rec.item_count=client.items.length;rec.outcome='child search passed';return;
        }
    }
}"""


def download_json(page, locator):
    with page.expect_download() as event:
        locator.click()
    return json.loads(Path(event.value.path()).read_text(encoding="utf-8"))


def search(page, mode):
    page.locator("#spatial-mode").select_option(mode)
    page.locator("#search").click()
    expect(page.locator("#search")).to_be_enabled()
    if "error" in (page.locator("#status").get_attribute("class") or "").split():
        raise RuntimeError(page.locator("#status").inner_text())
    return {"count": page.locator(".result-card").count(), "status": page.locator("#status").inner_text()}


def presets(page, out):
    results, items, errors, observed = [], {}, [], []
    def page_error(error):
        errors.append(str(error))
    def metadata_response(response):
        if response.request.resource_type != 'fetch' or not response.ok:
            return
        try:
            data = response.json()
            if isinstance(data, dict):
                observed.append({'url': response.url, 'data': data})
        except Exception:
            pass
    page.on('pageerror', page_error)
    page.on('response', metadata_response)
    for preset, collection, bbox, start, end in CASES:
        rec = {"preset": preset, "collection": collection, "checks": {}}
        results.append(rec)
        errors.clear()
        observed.clear()
        try:
            page.locator("#preset").select_option(preset)
            page.locator("#connect").click()
            expect(page.locator("#connect")).to_be_enabled()
            rec["connection"] = page.locator("#catalog-summary").inner_text()
            rec["status"] = page.locator("#status").inner_text()
            if page.locator("#search").is_disabled():
                rec["outcome"] = "connection unavailable"
                continue
            checks = rec["checks"]
            rec["collections"] = page.locator("#collection option").count() - 1
            checks["alphabetical"] = page.locator("#collection").evaluate("""e => {
                const a = [...e.options].slice(1).map(x => x.text);
                return a.every((x,i) => !i || a[i-1].localeCompare(x, undefined, {sensitivity:'base',numeric:true}) <= 0);
            }""")
            before_bbox = page.locator('#bbox').input_value()
            page.locator("#collection").select_option(collection)
            advertised = next((c for r in reversed(observed) for c in
                               (r['data'].get('collections', []) if isinstance(r['data'].get('collections'), list) else [r['data']])
                               if isinstance(c, dict) and c.get('id') == collection), None)
            rec["date_defaults"] = {"from": page.locator("#start").input_value(), "until": page.locator("#end").input_value()}
            expected = collection_expectations(advertised) if advertised is not None else None
            rec['advertised_collection_defaults'] = expected or {'outcome': 'collection response unavailable; unverified'}
            checks['from_advertised_extent'] = rec['date_defaults']['from'] == expected['from'] if expected else None
            today = page.evaluate("""() => {const d=new Date();return [d.getFullYear(),d.getMonth()+1,d.getDate()]
                .map((n,i)=>String(n).padStart(i?2:4,'0')).join('-');}""")
            checks["until_today"] = rec["date_defaults"]["until"] == today
            control_enabled = page.locator("#collection-area").is_enabled()
            if expected and expected['extent'] == 'usable' and control_enabled:
                page.locator("#collection-area").click()
            rec["collection_bbox"] = page.locator("#bbox").input_value()
            if expected:
                checks['collection_extent_control'] = control_enabled == (expected['extent'] == 'usable')
                if expected['extent'] == 'usable':
                    checks['collection_bbox'] = list(map(float, rec['collection_bbox'].split(','))) == expected['bbox']
                else:
                    checks['collection_bbox'] = rec['collection_bbox'] == before_bbox
                    expected_status = {'absent or invalid': 'no usable spatial extent', 'crossing antimeridian': 'crosses the antimeridian', 'point or line': 'point or line'}[expected['extent']]
                    checks['unsupported_extent_message'] = expected_status in page.locator('#status').inner_text()
            else:
                checks['collection_extent_control'] = checks['collection_bbox'] = None
            page.locator("#bbox").fill(bbox)
            page.locator("#bbox").dispatch_event("change")
            page.locator("#start").fill(start)
            page.locator("#end").fill(end)
            page.locator("#limit").select_option("10")
            rec["bbox_search"] = search(page, "bbox")
            if not rec["bbox_search"]["count"]:
                rec["outcome"] = "valid empty search; remaining item checks unverified"
                continue
            exported = download_json(page, page.locator("#export-geojson"))
            query = download_json(page, page.locator("#export-query"))
            checks["geojson_export"] = len(exported.get("features", [])) == rec["bbox_search"]["count"]
            checks["query_export"] = query.get("spatial_mode") == "bbox"
            page.locator(".result-card").first.click()
            item = download_json(page, page.get_by_role("button", name="Download item metadata (.json)", exact=True))
            checks["item_metadata_download"] = item.get("id") == exported["features"][0].get("id")
            items[preset] = exported['features'][0]  # Portable addresses, in memory only.
            rec["asset_links"] = page.locator(".dataset-downloads a").count()
            rec["clip_controls"] = page.locator(".asset-clip").count()
            if page.locator("#more").is_visible():
                response = next((r for r in reversed(observed) if r['data'].get('type') == 'FeatureCollection'), None)
                advertised_next = expected_next(response, query['requests'][-1]) if response and query.get('requests') else None
                page.locator("#more").click()
                expect(page.locator("#search")).to_be_enabled()
                rec["pagination_count"] = page.locator(".result-card").count()
                after = download_json(page, page.locator('#export-query'))
                checks["pagination"] = pagination_matches(query, after, advertised_next) and "error" not in (page.locator("#status").get_attribute("class") or "").split()
                rec['pagination_history_count'] = len(after.get('requests', []))
            else:
                rec["pagination"] = "not advertised; unverified live"
            w, s, e, n = map(float, bbox.split(","))
            if not page.locator("#vertices").is_visible():
                page.locator(".coordinate-editor summary").click()
            page.locator("#vertices").fill(f"{w}, {s}\n{e}, {s}\n{(w+e)/2}, {n}")
            page.locator("#apply-vertices").click()
            polygon = {'type': 'Polygon', 'coordinates': [[[w, s], [e, s], [(w+e)/2, n], [w, s]]]}
            for mode, label in [('polygon', 'polygon_search'), ('none', 'unfiltered_search')]:
                try:
                    rec[label] = search(page, mode)
                    if rec[label]['count']:
                        completed = download_json(page, page.locator('#export-query'))
                        checks[mode + '_query'] = spatial_query_matches(completed, mode, polygon)
                    else:
                        checks[mode + '_query'] = None
                        rec[label]['outcome'] = 'valid empty search; completed-query export unverified'
                except Exception as exc:
                    checks[mode + '_query'] = False
                    rec[label] = {'outcome': 'check failed', 'error': str(exc)[:2000]}
            rec["outcome"] = ('check failed' if any(v is False for v in checks.values()) else
                              'limited; some checks unverified' if any(v is None for v in checks.values()) else 'passed')
        except Exception as exc:
            rec["outcome"], rec["error"] = "check failed", str(exc)[:2000]
        finally:
            rec["page_errors"] = list(errors)
            if errors:
                rec["outcome"] = "check failed"
            write_json(out / "presets.json", results)
            print(f"{preset}: {rec['outcome']}", flush=True)
    page.remove_listener('pageerror', page_error)
    page.remove_listener('response', metadata_response)
    return results, items


def directory(page, out):
    rows = page.evaluate("async () => (await (await fetch('./public-catalogs.json', {credentials:'omit'})).json()).catalogs")
    results = []

    def record(result):
        results.append(result)
        write_json(out / "directory.json", results)
        print(json.dumps(redact({"tested": len(results), "total": len(rows), "title": result["title"], "outcome": result["outcome"]}), ensure_ascii=True), flush=True)

    page.expose_function("auditRecord", record)
    page.evaluate("""async rows => {
        const {STACClient}=await import('./stac.js');
        const {endpointProblem}=await import('./catalog-directory.js');
        const probeStatic=__STATIC_PROBE__;
        let cursor=0;
        async function worker() {
            while(cursor<rows.length) {
                const row=rows[cursor++], rec={id:row.id,slug:row.slug,title:row.title,requests:0};
                const problem=endpointProblem(row.url);
                if(problem) {rec.outcome='invalid listed endpoint';rec.error=problem;await window.auditRecord(rec);continue;}
                const client=new STACClient(async(url,options) => {
                    rec.requests++;
                    const response=await fetch(url,options);rec.last_http=response.status;
                    return {ok:response.ok,status:response.status,url:response.url,json:async() => {
                        const reader=response.body.getReader();let bytes=0;const chunks=[];
                        try {
                            while(true) {
                                const {done,value}=await reader.read();if(done)break;
                                bytes+=value.length;
                                if(bytes>8*1024*1024) {rec.audit_size_cap=true;throw Error('Audit metadata size cap (8 MiB)');}
                                chunks.push(value);
                            }
                        } finally {await reader.cancel().catch(()=>{});}
                        const joined=new Uint8Array(bytes);let offset=0;
                        for(const chunk of chunks) {joined.set(chunk,offset);offset+=chunk.length;}
                        return JSON.parse(new TextDecoder().decode(joined));
                    }};
                });
                try {
                    await client.connect(row.url);rec.root_type=client.root.type;
                    rec.collections=client.collections.length;rec.search_advertised=!!client.searchLink;
                    rec.outcome='connected; depth cap';
                    if(client.searchLink) {
                        await client.search({collection:client.collections[0]?.id,limit:1});
                        rec.item_count=client.items.length;rec.pagination_advertised=!!client.next;rec.outcome='search passed';
                    } else await probeStatic(client, rec);
                    if(client.items[0]) {
                        const item=client.geojson().features[0];rec.item_id=item.id;
                        rec.asset_count=Object.keys(item.assets||{}).length;rec.export_count=client.provenance().count;
                    }
                } catch(error) {
                    rec.outcome=rec.root_type?'navigation/search failed':'connection failed';rec.error=String(error.message);
                }
                await window.auditRecord(rec);
            }
        }
        await Promise.all(Array.from({length:4},worker));
    }""".replace('__STATIC_PROBE__', STATIC_PROBE_JS), rows)
    return results


def assets(page, items, out):
    results = []
    def record(result):
        results.append(result)
        write_json(out / 'assets.json', results)
    for provider, key in [("worldpop", "grid_l1"), ("earthsearch", "red"), ("planetary", "B04"), ("copernicus", "Product")]:
        item = items.get(provider, {})
        item_assets = item.get('assets')
        url = asset_address(item_assets.get(key)) if isinstance(item_assets, dict) else None
        if not url:
            record({"provider": provider, 'asset': key, "outcome": "no usable sample asset access; unverified"})
            continue
        result = page.evaluate("""async url => {
            try {
                const r=await fetch(url,{headers:{Range:'bytes=0-15'},credentials:'omit',signal:AbortSignal.timeout(20000)});
                const out={status:r.status,content_range:r.headers.get('content-range')};
                if(r.status===206) {
                    let bytes=0;const reader=r.body.getReader();
                    try {while(bytes<=16) {const v=await reader.read();if(v.done)break;bytes+=v.value.length;}}
                    finally {await reader.cancel().catch(()=>{});}
                    out.bytes=bytes;
                } else await r.body?.cancel();
                return out;
            } catch(e) {return {error:e.message};}
        }""", url)
        record({"provider": provider, "asset": key, **result})
        if provider == "earthsearch" and result.get("status") == 206 and result.get("bytes") == 16:
            bbox = tiny_crop_bbox(item)
            if bbox is None:
                record({'earthsearch_crop': {'outcome': 'missing or unsupported item bbox; unverified'}})
                continue
            crop = page.evaluate("""async request => {
                try {
                    const {startRasterClip}=await import('./raster-clip.js');
                    const result=await startRasterClip(request).promise;window.auditCrop=result.buffer;
                    return {width:result.width,height:result.height,epsg:result.epsg,bytes:result.buffer.byteLength,bounds:result.bounds};
                } catch(e) {return {error:e.message};}
            }""", {"url": url, "bbox": bbox, "provenance": {"audit": "anonymous live smoke"}})
            record({"earthsearch_crop": crop})
            if "error" not in crop:
                data = page.evaluate("() => Array.from(new Uint8Array(window.auditCrop))")
                (out / "earthsearch-crop.tif").write_bytes(bytes(data))
                page.evaluate("() => {delete window.auditCrop;}")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-url", default=SITE, help="Explorer URL, including its /explorer/ path")
    parser.add_argument("--chrome", help="Installed Chrome path; otherwise use Playwright Chromium")
    parser.add_argument("--output", type=Path, default=ROOT / "test-results/live-catalogs")
    parser.add_argument("--directory", action="store_true", help="Probe all bundled listings, four requests in parallel")
    parser.add_argument("--assets", action="store_true", help="Probe 16-byte ranges and a tiny public crop")
    parser.add_argument("--source", action="store_true", help="Serve only this app's web/ files from disk at the site origin; provider requests remain live")
    args = parser.parse_args()
    site = args.site_url.rstrip("/") + "/"
    enabled = ['presets', 'directory_ui'] + (['assets'] if args.assets else []) + (['directory'] if args.directory else [])
    out, summary = run_manifest(args.output, args.source, enabled)
    site_parts = urlsplit(site)
    summary['origin'] = {'scheme': site_parts.scheme, 'host': site_parts.hostname,
                         'port': site_parts.port or (443 if site_parts.scheme == 'https' else 80)}
    summary['explorer_path'] = site_parts.path
    write_json(out / 'audit.json', summary)
    expect.set_options(timeout=30000)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, **({"executable_path": args.chrome} if args.chrome else {}))
            summary['browser_version'] = browser.version
            context = browser.new_context(viewport={"width": 1440, "height": 1100}, accept_downloads=True, service_workers="block")
            if args.source:
                context.route(site + '**', lambda route: source_route(route, site))
            page = context.new_page()
            page.set_default_timeout(30000)
            summary['phase'] = 'app load'
            page.goto(site, wait_until="domcontentloaded")
            expect(page.locator("#connect")).to_be_enabled()
            summary['phase'] = 'presets'
            featured, items = presets(page, out)
            summary["featured"] = {r["preset"]: r["outcome"] for r in featured}
            summary['phase'] = 'directory_ui'
            try:
                page.locator("#preset").select_option("directory")
                expect(page.locator("#directory-catalog")).to_be_enabled()
                count = page.locator("#directory-count").inner_text()
                page.locator("#directory-filter").fill("Earth Search")
                matches = page.locator("#directory-catalog option").all_text_contents()
                page.locator("#directory-refresh").click()
                expect(page.locator("#directory-refresh")).to_be_enabled()
                summary["directory_ui"] = {"count": count, "filter_matches": matches, "refresh": page.locator("#directory-status").inner_text()}
            except Exception as exc:
                summary["directory_ui"] = {"error": str(exc)}
            if args.assets:
                summary['phase'] = 'assets'
                summary["assets"] = assets(page, items, out)
            if args.directory:
                summary['phase'] = 'directory'
                results = directory(page, out)
                summary["directory_count"] = len(results)
                summary["directory_outcomes"] = {key: sum(r["outcome"] == key for r in results) for key in sorted({r["outcome"] for r in results})}
            browser.close()
            summary.update(status='complete', phase='finished')
    except Exception as exc:
        summary['harness_error'] = {'type': type(exc).__name__, 'message': str(exc)[:2000]}
    finally:
        summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(out / "audit.json", summary)
    print(f"Audit {summary['status']}: {out}. Inspect JSON outcomes; completion is not a provider-health assertion.")
    return 0 if summary['status'] == 'complete' else 1


if __name__ == "__main__":
    raise SystemExit(main())
