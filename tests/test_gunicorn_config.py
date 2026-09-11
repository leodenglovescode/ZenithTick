from __future__ import annotations

import os
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


CONFIG_PATH = Path(__file__).resolve().parents[1] / "web" / "gunicorn_config.py"


class GunicornConfigTests(unittest.TestCase):
    def test_accepts_explicit_private_address(self) -> None:
        with patch.dict(
            os.environ,
            {"ZENITICK_BIND": "10.23.45.67", "ZENITICK_PORT": "8080"},
            clear=False,
        ):
            config = runpy.run_path(str(CONFIG_PATH))
        self.assertEqual(config["bind"], "10.23.45.67:8080")
        self.assertEqual(config["workers"], 1)

    def test_rejects_wildcard_address(self) -> None:
        with patch.dict(
            os.environ,
            {"ZENITICK_BIND": "0.0.0.0", "ZENITICK_PORT": "8080"},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "private RFC1918"):
                runpy.run_path(str(CONFIG_PATH))


if __name__ == "__main__":
    unittest.main()
