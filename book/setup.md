# Start in the browser

Open the site’s **Explorer** for the map, or **Run notebooks** for JupyterLite. In JupyterLite, open `01_launch_map.ipynb` and choose **Run → Run All Cells**. The kernel is **Python (Pyodide)**; initial startup downloads the runtime and can take a minute. Continue with the WorldPop and other-catalog tutorials in order.

JupyterLite stores notebook edits and new files in browser storage. Download anything you want to keep using the file browser’s context menu. Clearing site data can remove local changes. The hosted notebooks are templates, and your edits are not committed to GitHub.

## Build a local copy

Install Python 3.11–3.13 and Node.js 22 or later. From a checkout:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/build.py
python -m http.server 8000 --directory _site
```

Open `http://localhost:8000/`. The HTTP server serves static files only; Python notebooks execute in browser WebAssembly. Build time requires package/theme downloads. Runtime uses external Pyodide files, public STAC APIs, map tiles, and optional web fonts.

To target GitHub Pages, build with `python scripts/build.py --base-url /JupyterLite-STAC-Browser`. The MyST book embeds that base into its generated asset URLs. Preview at the same subpath or rebuild without a base for root hosting. Explorer, landing-page and notebook links resolve relative to their deployment.

## Automated verification

```bash
python -m playwright install chromium
python tests/browser_check.py
```

Fixture tests do not depend on remote catalogs. Live provider and JupyterLite runtime checks are separate because availability and CORS policy are outside this project’s control. Pull requests build and test the site; pushes to `main` deploy the successful artifact using GitHub Pages Actions. A local build alone does not publish it.
