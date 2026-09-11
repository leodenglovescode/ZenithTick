from __future__ import annotations

import stat
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "install.sh"


class InstallerTests(unittest.TestCase):
    def test_installer_is_executable_and_has_valid_bash_syntax(self) -> None:
        self.assertTrue(INSTALLER.stat().st_mode & stat.S_IXUSR)
        subprocess.run(["bash", "-n", str(INSTALLER)], check=True)

    def test_help_lists_lifecycle_actions(self) -> None:
        result = subprocess.run(
            ["bash", str(INSTALLER), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        for action in ("install", "update", "uninstall", "status", "auto-update"):
            self.assertIn(action, result.stdout)

    def test_update_timer_is_daily_and_persistent(self) -> None:
        timer = (PROJECT_ROOT / "systemd" / "zenitick-update.timer").read_text()
        self.assertIn("OnCalendar=daily", timer)
        self.assertIn("Persistent=yes", timer)
        self.assertIn("RandomizedDelaySec=1h", timer)


if __name__ == "__main__":
    unittest.main()
