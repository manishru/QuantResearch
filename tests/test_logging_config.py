import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from quantresearch.logging_config import configure_logging


class LoggingTests(TestCase):
    def tearDown(self) -> None:
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()

    def test_configure_logging_writes_file(self) -> None:
        with TemporaryDirectory() as directory:
            log_file = configure_logging(Path(directory), "DEBUG", console=False)
            logging.getLogger("test").info("hello infrastructure")
            for handler in logging.getLogger().handlers:
                handler.flush()
            self.assertTrue(log_file.exists())
            self.assertIn("hello infrastructure", log_file.read_text(encoding="utf-8"))
