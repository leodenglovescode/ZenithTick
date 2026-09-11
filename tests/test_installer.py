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

    def test_port_conflicts_preserve_unrelated_processes(self) -> None:
        installer = INSTALLER.read_text()
        self.assertIn("service_owns_port", installer)
        self.assertIn("/proc/${listener_pid}/cgroup", installer)
        self.assertIn("will not stop or signal an unrelated process", installer)
        self.assertNotIn('kill -TERM "${pid}"', installer)

    def test_default_port_conflicts_have_a_confirmed_fallback(self) -> None:
        installer = INSTALLER.read_text()
        self.assertIn("Use available port ${candidate} instead? [Y/n]", installer)
        self.assertIn("using available port", installer)
        self.assertIn("The explicitly requested port is occupied", installer)

    def test_failed_health_check_stops_zenitick_restart_loop(self) -> None:
        installer = INSTALLER.read_text()
        status_index = installer.index('journalctl -u "${SERVICE_NAME}" -n 30')
        stop_index = installer.index('systemctl stop "${SERVICE_NAME}"', status_index)
        failure_index = installer.index('die "ZenithTick did not pass', stop_index)
        self.assertLess(status_index, stop_index)
        self.assertLess(stop_index, failure_index)

    def test_health_check_cannot_inherit_a_network_preload(self) -> None:
        installer = INSTALLER.read_text()
        self.assertIn("env -u LD_PRELOAD curl --noproxy '*'", installer)

    def test_update_timer_is_daily_and_persistent(self) -> None:
        timer = (PROJECT_ROOT / "systemd" / "zenitick-update.timer").read_text()
        self.assertIn("OnCalendar=daily", timer)
        self.assertIn("Persistent=yes", timer)
        self.assertIn("RandomizedDelaySec=1h", timer)


if __name__ == "__main__":
    unittest.main()
