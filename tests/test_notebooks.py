from pathlib import Path
import ast
import contextlib
import io
import json
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import nbformat

ROOT = Path(__file__).resolve().parents[1]


class NotebookTests(unittest.TestCase):
    def test_notebooks_are_valid_and_executable_python(self):
        paths = sorted((ROOT / "notebooks").glob("*.ipynb"))
        self.assertEqual([path.name for path in paths], [
            "01_launch_map.ipynb", "02_worldpop_search.ipynb", "03_other_catalogs_and_export.ipynb",
            "04_discover_download_rustgis.ipynb", "05_discover_download_geolibre.ipynb",
        ])
        for path in paths:
            notebook = nbformat.read(path, as_version=4)
            nbformat.validate(notebook)
            self.assertEqual(notebook.metadata.kernelspec.language, "python")
            for cell in notebook.cells:
                if cell.cell_type == "code":
                    compile(cell.source, str(path), "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                    self.assertEqual(cell.outputs, [])

    def test_gis_handoff_tutorials_are_explicit_and_user_activated(self):
        for name, destination, prefix, marker in [
            ("04_discover_download_rustgis.ipynb", "handoff['rustgis']", "rustgis-tutorial", "RustGIS workflow ready"),
            ("05_discover_download_geolibre.ipynb", "handoff['geolibre']", "geolibre-tutorial", "GeoLibre workflow ready"),
        ]:
            notebook = nbformat.read(ROOT / "notebooks" / name, as_version=4)
            source = "\n".join(cell.source for cell in notebook.cells)
            self.assertIn("client.public_cog_handoff(item", source)
            self.assertIn("handoff['download']", source)
            self.assertIn(destination, source)
            self.assertIn("target=\"_blank\"", source)
            self.assertIn("rel=\"noopener noreferrer\"", source)
            self.assertIn("Retry or choose another catalog", source)
            self.assertIn("never fabricates results", source)
            self.assertIn("Selected candidate asset:", source)
            self.assertIn("Collection license:", source)
            self.assertIn("Collection providers:", source)
            self.assertIn("Download selected GeoTIFF/COG candidate", source)
            self.assertNotIn("Download selected COG", source)
            self.assertIn(f"client.save('{prefix}')", source)
            self.assertIn(f"'{prefix}-items.geojson'", source)
            self.assertIn(f"'{prefix}-search.json'", source)
            self.assertIn("json.loads(Path(saved_name).read_text", source)
            self.assertIn(marker, source)
            self.assertNotIn("await pyfetch", source)
            self.assertNotIn("requests.get", source)

    def test_generator_reproduces_checked_in_notebooks(self):
        with TemporaryDirectory() as directory:
            isolated = Path(directory)
            (isolated / "scripts").mkdir()
            (isolated / "notebooks").mkdir()
            generator = isolated / "scripts" / "create_notebooks.py"
            shutil.copy2(ROOT / "scripts" / "create_notebooks.py", generator)
            subprocess.run([sys.executable, str(generator)], cwd=isolated, check=True, capture_output=True, text=True)
            for checked_in in sorted((ROOT / "notebooks").glob("*.ipynb")):
                generated = isolated / "notebooks" / checked_in.name
                self.assertTrue(generated.is_file(), checked_in.name)
                self.assertEqual(json.loads(generated.read_text(encoding="utf-8")),
                                 json.loads(checked_in.read_text(encoding="utf-8")))

    def test_four_sources_and_attribution(self):
        references = ["github.com/developmentseed/stac-map", "pystac-client.readthedocs.io/en/stable/", "stacmap.readthedocs.io/en/latest/tutorials/quickstart.html", "nbviewer.org/github/microsoft/PlanetaryComputerExamples/blob/main/tutorials/interactive-browser.ipynb"]
        for name in ["README.md", "book/references.md"]:
            text = (ROOT / name).read_text(encoding="utf-8")
            for reference in references:
                self.assertIn(reference, text)
            self.assertIn("OpenStreetMap", text)
            self.assertIn("WorldPop", text)


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_static_and_api_provenance_replay_examples(self):
        notebook = nbformat.read(ROOT / "notebooks/03_other_catalogs_and_export.ipynb", as_version=4)
        source = next(cell.source for cell in notebook.cells if cell.cell_type == "code" and "async def replay_saved" in cell.source)
        instances = []

        class ReplayClient:
            def __init__(self, url):
                self.url = url
                self.items = []
                instances.append(self)

            async def connect(self):
                return self

            async def open_link(self, link):
                self.link = link
                self.items = [{"id": "static-fixture"}]

            async def search(self, **query):
                self.query = query
                return [{"id": "api-fixture"}]

            def provenance(self):
                return {"stac_root": self.url, "query": None, "requests": [{"url": "https://fixture.test/items/item.json", "method": "GET"}]}

        client = ReplayClient("https://fixture.test/catalog.json")
        scope = {"STACBrowser": ReplayClient, "client": client}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(source, "tutorial03 replay cell", "exec"), scope)
        self.assertEqual(await scope["replay_saved"](client.provenance()), [{"id": "static-fixture"}])
        self.assertEqual(instances[-1].link, {"rel": "item", "href": "https://fixture.test/items/item.json"})
        saved = {"stac_root": "https://fixture.test/", "query": {"bbox": [0, 0, 1, 1], "collections": ["TEST"], "limit": 5,
                 "datetime": "2020-01-01T00:00:00Z/2020-01-02T23:59:59.999999Z"}}
        self.assertEqual(await scope["replay_saved"](saved), [{"id": "api-fixture"}])
        self.assertEqual(instances[-1].query, {"bbox": [0, 0, 1, 1], "intersects": None, "study_area": None, "collection": "TEST", "limit": 5, "start": "2020-01-01", "end": "2020-01-02"})
        polygon = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
        del saved['query']['bbox']
        saved['query']['intersects'] = polygon
        saved['study_area'] = {'shape': 'polygon', 'geometry': polygon}
        await scope['replay_saved'](saved)
        self.assertIsNone(instances[-1].query['bbox'])
        self.assertEqual(instances[-1].query['intersects'], polygon)
        self.assertEqual(instances[-1].query['study_area'], saved['study_area'])
        del saved['query']['intersects']
        await scope['replay_saved'](saved)
        self.assertIsNone(instances[-1].query['bbox'])
        self.assertIsNone(instances[-1].query['intersects'])


if __name__ == "__main__":
    unittest.main()
