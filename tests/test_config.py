from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from quantresearch.config import Settings


class SettingsTests(TestCase):
    def test_defaults_are_root_relative(self) -> None:
        with TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            root = Path(directory).resolve()
            settings = Settings.from_env(root)
            self.assertEqual(settings.data_dir, root / "data")
            self.assertEqual(settings.raw_data_dir, root / "data" / "raw")
            self.assertEqual(settings.logs_dir, root / "logs")
            self.assertEqual(
                settings.research_db_path,
                root / "data" / "features" / "research.duckdb",
            )

    def test_environment_override_is_expanded(self) -> None:
        with TemporaryDirectory() as directory:
            override = Path(directory) / "custom-data"
            with patch.dict("os.environ", {"QUANTRESEARCH_DATA_DIR": str(override)}, clear=True):
                settings = Settings.from_env(Path(directory) / "project")
            self.assertEqual(settings.data_dir, override.resolve())
            self.assertEqual(settings.raw_data_dir, override.resolve() / "raw")

    def test_invalid_log_level_is_rejected(self) -> None:
        with patch.dict("os.environ", {"QUANTRESEARCH_LOG_LEVEL": "LOUD"}, clear=True):
            with self.assertRaises(ValueError):
                Settings.from_env(Path.cwd())

    def test_ensure_directories_creates_runtime_paths(self) -> None:
        with TemporaryDirectory() as directory:
            settings = Settings.from_env(Path(directory))
            settings.ensure_directories()
            self.assertTrue(settings.feature_data_dir.is_dir())
            self.assertTrue(settings.reports_dir.is_dir())
