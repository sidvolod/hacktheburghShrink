"""Clean-checkout launch must use the published demo without acquiring raw data."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import launch


class DemoLaunchTests(unittest.TestCase):
    def snapshot(self, root: Path) -> Path:
        public = root / "data/app-public"
        (public / "data").mkdir(parents=True)
        (public / "images").mkdir()
        (public / "images/pack.jpg").write_bytes(b"fixture image")
        document = {"schema_version": 1, "cases": [{"photos": [{"local_path": "/images/pack.jpg"}]}],
            "histories": [], "comparisons": [], "category_forecast": {"schema_version": 1}}
        (public / "data/demo.json").write_text(json.dumps(document))
        for name in ("evaluation", "monthly-audit", "source-registry", "category-forecast"):
            (public / f"data/{name}.json").write_text("{}")
        return public

    def test_default_launch_needs_no_processed_tables_or_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            public = self.snapshot(root)
            with patch.object(launch, "refresh_research_data") as refresh:
                self.assertEqual(launch.prepare_demo(root, {}), (public / "data/demo.json").resolve())
            refresh.assert_not_called()
            self.assertFalse((root / "data/processed").exists())

    def test_explicit_refresh_precedes_snapshot_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(launch, "refresh_research_data", side_effect=lambda r, env: self.snapshot(r)) as refresh:
                launch.prepare_demo(root, {"fixture": "yes"}, refresh_data=True)
            refresh.assert_called_once_with(root, {"fixture": "yes"})

    def test_missing_or_malformed_snapshot_explains_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(RuntimeError, "--refresh-data"):
                launch.prepare_demo(root, {})
            public = self.snapshot(root)
            (public / "data/demo.json").write_text("invalid json")
            with self.assertRaisesRegex(RuntimeError, "--refresh-data"):
                launch.prepare_demo(root, {})

    def test_missing_linked_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            public = self.snapshot(root)
            (public / "data/category-forecast.json").unlink()
            with self.assertRaisesRegex(RuntimeError, "category-forecast.json"):
                launch.prepare_demo(root, {})

    def test_missing_photo_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            public = self.snapshot(root)
            (public / "images/pack.jpg").unlink()
            with self.assertRaisesRegex(RuntimeError, "images/pack.jpg"):
                launch.prepare_demo(root, {})

    def test_local_asset_cannot_escape_public_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            public = self.snapshot(root)
            outside = root / "outside.jpg"
            outside.write_bytes(b"outside fixture")
            path = public / "data/demo.json"
            document = json.loads(path.read_text())
            document["cases"][0]["photos"][0]["local_path"] = "/../../outside.jpg"
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(RuntimeError, "Invalid|invalid"):
                launch.prepare_demo(root, {})


if __name__ == "__main__":
    unittest.main()
