"""Regression coverage for delayed schedules and automatic regeneration."""

from datetime import datetime, timezone, timedelta
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


window = load("monitor-window")
guards = load("maintain-workflow-guards")


class MonitoringTests(unittest.TestCase):
    def test_window_boundaries_in_winter_summer_and_on_clock_change_days(self):
        for day in ["2026-01-15", "2026-07-15", "2026-03-29", "2026-10-25"]:
            for clock, allowed in [
                ("00:00:00", False),
                ("05:59:59", False),
                ("06:00:00", True),
                ("12:00:00", True),
                ("23:30:00", True),
                ("23:57:59", True),
                ("23:58:00", True),
                ("23:58:01", False),
                ("23:59:59", False),
            ]:
                local = datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
                with self.subTest(local=local):
                    self.assertEqual(window.can_check(local.astimezone(timezone.utc)), allowed)

    def test_dst_changes_utc_start_time(self):
        for stamp, allowed in [
            ("2026-07-15T03:59:59+00:00", False),
            ("2026-07-15T04:00:00+00:00", True),
            ("2026-01-15T04:59:59+00:00", False),
            ("2026-01-15T05:00:00+00:00", True),
            ("2026-07-15T22:00:00+00:00", False),
            ("2026-01-15T23:00:00+00:00", False),
        ]:
            with self.subTest(stamp=stamp):
                self.assertEqual(window.can_check(datetime.fromisoformat(stamp)), allowed)

    def test_timeouts_stop_before_midnight(self):
        for clock, expected in [("06:00:00", 30), ("23:30:00", 29), ("23:55:00", 4), ("23:57:59", 1), ("00:00:00", 0)]:
            stamp = datetime.fromisoformat(f"2026-10-06T{clock}+02:00")
            self.assertEqual(window.timeout_minutes(stamp), expected)

    def test_naive_clock_is_rejected(self):
        with self.assertRaises(ValueError):
            window.can_check(datetime(2026, 10, 6, 12))

    def test_command_emits_a_valid_timeout_even_when_skipped(self):
        import runpy
        for clock, allowed, timeout in [("12:00", "true", "30"), ("02:00", "false", "1"), ("23:55", "true", "4")]:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                summary = Path(directory) / "summary"
                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return datetime.fromisoformat(f"2026-10-06T{clock}:00+02:00").astimezone(tz)
                with patch("datetime.datetime", Clock), patch.dict(os.environ, {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)}):
                    runpy.run_path(str(Path(__file__).with_name("monitor-window.py")), run_name="__main__")
                self.assertEqual(output.read_text(), f"allowed={allowed}\ntimeout_minutes={timeout}\n")
                self.assertIn("Europe/Amsterdam", summary.read_text())

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
                generated = original.replace(guards.GATE, "").replace(guards.CONDITION, "").replace(guards.HOOK, "").replace(guards.SCHEDULE_TIMEZONE, "")
                generated = re.sub(r"@v\d+\.\d+\.\d+", "@v99.0.0", generated)
                guarded = guards.patch_workflow(name, generated)
                self.assertEqual(guards.patch_workflow(name, guarded), guarded)
                self.assertIn("@v99.0.0" if "@v99.0.0" in generated else "@master", guarded)
                if name in guards.MONITORS:
                    self.assertEqual(guarded.count(guards.GATE), 1)
                    self.assertEqual(guarded.count(guards.CONDITION), 1)
                if name in guards.UPDATERS:
                    self.assertEqual(guarded.count(guards.HOOK), 1)
                if name in {"uptime.yml", "response-time.yml"}:
                    self.assertEqual(guarded.count(guards.SCHEDULE_TIMEZONE), 1)
                self.assertEqual(guarded.replace(guards.GATE, "").replace(guards.CONDITION, "").replace(guards.HOOK, "").replace(guards.SCHEDULE_TIMEZONE, ""), generated)

    def test_legacy_guard_is_migrated(self):
        for name in guards.MONITORS:
            current = (guards.ROOT / ".github/workflows" / name).read_text()
            old = current.replace(guards.CONDITION, guards.LEGACY_CONDITION).replace(guards.SCHEDULE_TIMEZONE, "")
            self.assertEqual(guards.patch_workflow(name, old), current)

    def test_schedule_matches_config_and_avoids_peak_minutes(self):
        config = (guards.ROOT / ".upptimerc.yml").read_text()
        for name, key in [("uptime.yml", "uptime"), ("response-time.yml", "responseTime")]:
            cron = re.search(rf'^  {key}: "([^"]+)"$', config, re.MULTILINE)[1]
            workflow = (guards.ROOT / ".github/workflows" / name).read_text()
            self.assertIn(f'    - cron: "{cron}"\n' + guards.SCHEDULE_TIMEZONE, workflow)
        self.assertIn('uptime: "2-59/5 6-23 * * *"', config)
        self.assertIn('responseTime: "17 12 * * *"', config)

    def test_upstream_layout_change_fails_closed(self):
        with self.assertRaises(ValueError):
            guards.patch_workflow("uptime.yml", "      - name: Renamed monitor step\n")

    def test_real_git_commit_preserves_guards_after_regeneration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy(guards.ROOT / ".upptimerc.yml", root / ".upptimerc.yml")
            shutil.copytree(guards.ROOT / ".github/scripts", root / ".github/scripts")
            shutil.copytree(guards.ROOT / ".githooks", root / ".githooks")
            (root / ".github/workflows").mkdir()
            for name in guards.MONITORS.keys() | guards.UPDATERS:
                source = (guards.ROOT / ".github/workflows" / name).read_text()
                generated = source.replace(guards.GATE, "").replace(guards.CONDITION, "").replace(guards.HOOK, "").replace(guards.SCHEDULE_TIMEZONE, "")
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
                self.assertIn(guards.CONDITION, committed)
                if name in {"uptime.yml", "response-time.yml"}:
                    self.assertIn(guards.SCHEDULE_TIMEZONE, committed)
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
