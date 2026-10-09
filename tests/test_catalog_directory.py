"""Directory normalization and failure-safe updater tests; no live network."""
from contextlib import redirect_stdout
import ast
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import update_catalog_directory as directory

CASES = json.loads((ROOT / "tests/fixtures/catalog-directory.json").read_text(encoding="utf-8"))


class DirectoryTests(unittest.IsolatedAsyncioTestCase):
    def test_shared_normalization_cases(self):
        for case in CASES["normalization"]:
            with self.subTest(case=case["name"]):
                if "ids" in case:
                    rows = directory.normalize_catalogs(case["input"])
                    self.assertEqual([r["id"] for r in rows], case["ids"])
                    for row in rows:
                        original = next(r for r in case["input"] if r["id"] == row["id"])
                        self.assertEqual(row, {key: original[key] for key in directory.FIELDS})
                else:
                    with self.assertRaises(ValueError):
                        directory.normalize_catalogs(case["input"])

    def test_snapshot_is_public_canonical_and_minimal(self):
        data = json.loads((ROOT / "web/public-catalogs.json").read_text(encoding="utf-8"))
        self.assertEqual(data, directory.snapshot(data["catalogs"], data["fetched_at"]))
        self.assertTrue(data["catalogs"])
        self.assertTrue(all(row["access"] == "public" for row in data["catalogs"]))

    def test_updater_failure_keeps_bytes_and_success_replaces(self):
        class Response(io.BytesIO):
            status = 200
            url = directory.API

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "public-catalogs.json"
            target.write_bytes(b"previous snapshot")
            malformed_slug = next(case["input"] for case in CASES["normalization"] if case["name"] == "lone surrogate slug")
            for raw in [b"<html>oops", b"{}", b"[]", b"[null]", json.dumps(malformed_slug).encode(), b"x" * (directory.MAX_BYTES + 1)]:
                with self.subTest(raw=raw[:20]):
                    with self.assertRaises(ValueError):
                        directory.update(target, lambda *args, **kwargs: Response(raw))
                    self.assertEqual(target.read_bytes(), b"previous snapshot")
            def timeout(*args, **kwargs):
                raise TimeoutError("timeout")
            with self.assertRaises(TimeoutError):
                directory.update(target, timeout)
            self.assertEqual(target.read_bytes(), b"previous snapshot")
            def success(request, timeout):
                self.assertEqual(request.full_url, directory.API)
                self.assertEqual(timeout, 20)
                return Response(json.dumps(CASES["normalization"][0]["input"]).encode())
            data = directory.update(target, success)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), data)
            self.assertEqual(len(list(Path(temp).iterdir())), 1)

    def test_notebook_directory_cell_reads_the_canonical_snapshot_without_requests(self):
        book = json.loads((ROOT / "notebooks/03_other_catalogs_and_export.ipynb").read_text())
        source = next("".join(c["source"]) for c in book["cells"] if c["cell_type"] == "code" and "directory = json.loads" in "".join(c["source"]))
        scope = {}
        with patch.object(Path, "read_text", return_value=(ROOT / "web/public-catalogs.json").read_text(encoding="utf-8")), redirect_stdout(io.StringIO()):
            exec(compile(source, "notebook directory cell", "exec"), scope)
        self.assertEqual(scope["directory"], json.loads((ROOT / "web/public-catalogs.json").read_text(encoding="utf-8")))
        self.assertTrue(scope["matches"])

    async def test_notebook_no_matches_guides_user_and_optional_connection_is_guarded(self):
        book = json.loads((ROOT / "notebooks/03_other_catalogs_and_export.ipynb").read_text())
        source = next("".join(c["source"]) for c in book["cells"] if c["cell_type"] == "code" and "directory = json.loads" in "".join(c["source"]))
        source = source.replace("keyword = 'earth'", "keyword = 'no-matching-public-listing-for-this-test'")
        source = source.replace("# if selected is not None:", "if selected is not None:").replace("#     ", "    ")
        scope = {"STACBrowser": lambda *_: self.fail("No-match example must not connect")}
        output = io.StringIO()
        with patch.object(Path, "read_text", return_value=(ROOT / "web/public-catalogs.json").read_text(encoding="utf-8")), redirect_stdout(output):
            await eval(compile(source, "notebook no-match example", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), scope)
        self.assertIsNone(scope["selected"])
        self.assertIn("No public listings match. Change keyword", output.getvalue())
