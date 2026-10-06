from pathlib import Path
import ast
import contextlib
import io
import unittest
import nbformat

ROOT = Path(__file__).resolve().parents[1]


class NotebookTests(unittest.TestCase):
    def test_notebooks_are_valid_and_executable_python(self):
        paths = sorted((ROOT / "notebooks").glob("*.ipynb"))
        self.assertEqual(len(paths), 3)
        for path in paths:
            notebook = nbformat.read(path, as_version=4)
            nbformat.validate(notebook)
            self.assertEqual(notebook.metadata.kernelspec.language, "python")
            for cell in notebook.cells:
                if cell.cell_type == "code":
                    compile(cell.source, str(path), "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                    self.assertEqual(cell.outputs, [])

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
        self.assertEqual(instances[-1].query, {"bbox": [0, 0, 1, 1], "collection": "TEST", "limit": 5, "start": "2020-01-01", "end": "2020-01-02"})


if __name__ == "__main__":
    unittest.main()
