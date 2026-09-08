"""Regression coverage for delayed schedules and automatic regeneration."""

from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


window = load("monitor-window")
guards = load("maintain-workflow-guards")


class MonitoringTests(unittest.TestCase):
    def test_window_boundaries(self):
        for stamp, allowed in [
            ("2026-09-08T00:29:59+00:00", True),
            ("2026-09-08T00:30:00+00:00", False),
            ("2026-09-08T01:00:00+00:00", False),
            ("2026-09-08T05:59:59+00:00", False),
            ("2026-09-08T06:00:00+00:00", True),
            ("2026-09-08T23:59:59+00:00", True),
        ]:
            with self.subTest(stamp=stamp):
                self.assertEqual(window.can_check(datetime.fromisoformat(stamp)), allowed)

    def test_incident_1724_delayed_start_is_blocked(self):
        self.assertFalse(window.can_check(datetime.fromisoformat("2026-09-08T01:06:37+00:00")))

    def test_timezone_does_not_change_the_window(self):
        instant = datetime(2026, 9, 8, 0, 45, tzinfo=timezone.utc)
        for offset in [2, 1, -4, 5.5]:
            self.assertFalse(window.can_check(instant.astimezone(timezone(timedelta(hours=offset)))))

    def test_template_regeneration_retains_upstream_changes_and_guard(self):
        for name in guards.MONITORS.keys() | guards.UPDATERS:
            with self.subTest(workflow=name):
                original = (guards.ROOT / ".github/workflows" / name).read_text()
                generated = original.replace(guards.GATE, "").replace(guards.CONDITION, "").replace(guards.HOOK, "")
                generated = generated.replace("@v1.44.0", "@v99.0.0")
                guarded = guards.patch_workflow(name, generated)
                self.assertEqual(guards.patch_workflow(name, guarded), guarded)
                self.assertIn("@v99.0.0" if "@v99.0.0" in generated else "@master", guarded)
                if name in guards.MONITORS:
                    self.assertEqual(guarded.count(guards.GATE), 1)
                    self.assertEqual(guarded.count(guards.CONDITION), 1)
                if name in guards.UPDATERS:
                    self.assertEqual(guarded.count(guards.HOOK), 1)
                self.assertEqual(guarded.replace(guards.GATE, "").replace(guards.CONDITION, "").replace(guards.HOOK, ""), generated)

    def test_upstream_layout_change_fails_closed(self):
        with self.assertRaises(ValueError):
            guards.patch_workflow("uptime.yml", "      - name: Renamed monitor step\n")

    def test_real_git_commit_preserves_guards_after_regeneration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(guards.ROOT / ".github/scripts", root / ".github/scripts")
            shutil.copytree(guards.ROOT / ".githooks", root / ".githooks")
            (root / ".github/workflows").mkdir()
            for name in guards.MONITORS.keys() | guards.UPDATERS:
                source = (guards.ROOT / ".github/workflows" / name).read_text()
                generated = source.replace(guards.GATE, "").replace(guards.CONDITION, "").replace(guards.HOOK, "")
                (root / ".github/workflows" / name).write_text(generated)

            def git(*args, check=True):
                return subprocess.run(["git", *args], cwd=root, check=check, capture_output=True, text=True)

            git("init", "-q")
            git("config", "core.hooksPath", ".githooks")
            git("config", "user.name", "Monitoring test")
            git("config", "user.email", "test@example.invalid")
            git("add", ".")
            git("-c", "commit.gpgsign=false", "commit", "-qm", "Simulated template update")
            for name in guards.MONITORS:
                committed = git("show", f"HEAD:.github/workflows/{name}").stdout
                self.assertIn(guards.GATE, committed)
            for name in guards.UPDATERS:
                committed = git("show", f"HEAD:.github/workflows/{name}").stdout
                self.assertIn(guards.HOOK, committed)

            before = git("rev-parse", "HEAD").stdout
            path = root / ".github/workflows/uptime.yml"
            path.write_text("      - name: Unexpected upstream layout\n")
            git("add", ".")
            result = git("-c", "commit.gpgsign=false", "commit", "-qm", "Must be rejected", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(git("rev-parse", "HEAD").stdout, before)


if __name__ == "__main__":
    unittest.main()
