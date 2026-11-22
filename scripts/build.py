"""Build a single static site; no application server is deployed."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, env=None):
    print("Running:", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def reset_staging(path):
    """Remove only a verified, named workspace staging directory."""
    staging_root = ROOT.resolve() / "_build"
    if path.name not in {"lite-contents", "book-source"} or path.resolve() != staging_root / path.name:
        raise ValueError(f"Refusing to reset staging outside {staging_root}: {path}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def write_relative_redirect(path, target):
    """Create a same-deployment redirect without assuming the site's origin or base path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = target.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    path.write_text(
        "<!doctype html><meta charset=\"utf-8\">"
        f"<meta http-equiv=\"refresh\" content=\"0; url={escaped}\">"
        f"<title>Redirecting</title><a href=\"{escaped}\">Continue</a>"
        f"<script>location.replace(new URL({json.dumps(target)}, location.href));</script>",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="", help="Host subpath, e.g. /JupyterLite-STAC-Browser (no trailing slash)")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if base and (not base.startswith("/") or ".." in base or "?" in base or "#" in base):
        parser.error("--base-url must be an absolute URL path")
    output = ROOT / "_site"
    if output.exists():
        # Fixed, resolved workspace-owned output path only.
        assert output.resolve().parent == ROOT.resolve()
        shutil.rmtree(output)
    output.mkdir()
    shutil.copytree(ROOT / "web", output / "explorer")
    shutil.copytree(ROOT / "assets", output / "assets")
    shutil.copy2(ROOT / "site-index.html", output / "index.html")
    (output / ".nojekyll").touch()
    contents = ROOT / "_build" / "lite-contents"
    reset_staging(contents)
    for source in (ROOT / "notebooks").iterdir():
        if source.is_file():
            shutil.copy2(source, contents / source.name)
    shutil.copy2(ROOT / "web/public-catalogs.json", contents / "public-catalogs.json")
    (contents / "site-config.json").write_text(json.dumps({"base_path": base}), encoding="utf-8")
    run(sys.executable, "-m", "jupyterlite_core", "build", "--contents", contents, "--output-dir", output / "lite")
    # Build in staging so notebooks can be included in the book without duplicate sources.
    book = ROOT / "_build" / "book-source"
    reset_staging(book)
    for source in (ROOT / "book").iterdir():
        if source.is_file():
            shutil.copy2(source, book / source.name)
    for source in (ROOT / "notebooks").glob("*.ipynb"):
        shutil.copy2(source, book / source.name)
    env = os.environ.copy()
    env["BASE_URL"] = base + "/book"
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    run(sys.executable, "-m", "jupyter_book", "build", "--html", "--strict", cwd=book, env=env)
    shutil.copytree(book / "_build" / "html", output / "book")
    # Current MyST prepends BASE_URL to internal nav entries, including the
    # legacy /../ sibling links. Keep those origin-agnostic nav destinations
    # working through tiny same-deployment redirects.
    write_relative_redirect(output / "book" / "explorer" / "index.html", "../../explorer/")
    write_relative_redirect(output / "book" / "lite" / "lab" / "index.html", "../../../lite/lab/index.html")
    for required in ["index.html", "explorer/index.html", "explorer/geolibre-bridge.html", "explorer/geolibre-bridge.js", "explorer/geolibre-bridge.css", "explorer/public-catalogs.json", "lite/lab/index.html", "book/index.html", "book/explorer/index.html", "book/lite/lab/index.html", "book/discover-download-rustgis/index.html", "book/discover-download-geolibre/index.html", "lite/files/stac_browser.py", "lite/files/site-config.json", "lite/files/public-catalogs.json", "lite/files/04_discover_download_rustgis.ipynb", "lite/files/05_discover_download_geolibre.ipynb"]:
        if not (output / required).is_file():
            raise RuntimeError(f"Build is missing {required}")
    print(f"Built {output}. Preview with: python -m http.server 8000 --directory _site")
    print(f"Book asset path: {base}/book. Deployment has not been performed.")


if __name__ == "__main__":
    main()
