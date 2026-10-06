"""Focused staging cleanup checks; no site build or network required."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build


class StagingTests(unittest.TestCase):
    def test_deleted_sources_and_old_generated_pages_are_removed(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(build, "ROOT", Path(temp)):
            for name in ["lite-contents", "book-source"]:
                stage = Path(temp) / "_build" / name
                (stage / "_build" / "html").mkdir(parents=True)
                (stage / "deleted.ipynb").write_text("old notebook")
                (stage / "_build" / "html" / "deleted.html").write_text("old page")
                build.reset_staging(stage)
                self.assertTrue(stage.is_dir())
                self.assertEqual(list(stage.iterdir()), [])
                (stage / "current.ipynb").write_text("new notebook")
                self.assertEqual([p.name for p in stage.iterdir()], ["current.ipynb"])

    def test_cleanup_rejects_outside_or_unnamed_paths(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(build, "ROOT", Path(temp)):
            outside = Path(temp) / "lite-contents"
            outside.mkdir()
            marker = outside / "keep.txt"
            marker.write_text("must survive")
            for target in [outside, Path(temp), Path(temp) / "_build" / "other"]:
                with self.assertRaises(ValueError):
                    build.reset_staging(target)
            self.assertTrue(marker.exists())
