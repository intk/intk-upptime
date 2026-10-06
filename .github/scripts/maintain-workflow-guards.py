"""Reapply runtime guards before Upptime commits regenerated workflows.

Keep the upstream workflow generator (including version and secret updates).
Abort if its step layout changes instead of publishing an unguarded monitor.
"""

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MONITORS = {
    "uptime.yml": "Check endpoint status",
    "response-time.yml": "Update response time",
    "setup.yml": "Update response time",
}
UPDATERS = {"setup.yml", "update-template.yml"}
WORKFLOWS = MONITORS.keys() | UPDATERS | {"graphs.yml", "site.yml", "summary.yml", "updates.yml"}
QUEUE = "  queue: max\n"
GATE = """      - name: Enforce overnight monitoring window
        id: monitor_window
        run: python3 .github/scripts/monitor-window.py
"""
CONDITION = """        if: steps.monitor_window.outputs.allowed == 'true'
        timeout-minutes: ${{ fromJSON(steps.monitor_window.outputs.timeout_minutes) }}
"""
LEGACY_CONDITION = """        if: steps.monitor_window.outputs.allowed == 'true'
        timeout-minutes: 30
"""
SCHEDULE_TIMEZONE = '      timezone: "Europe/Amsterdam"\n'
HOOK = """      - name: Preserve monitoring guards during template updates
        run: git config --local core.hooksPath .githooks
"""


def patch_workflow(name, text):
    # Normalize our additions so rerunning this is idempotent.
    text = text.replace(GATE, "").replace(CONDITION, "").replace(HOOK, "")
    text = text.replace(LEGACY_CONDITION, "")
    if name in WORKFLOWS:
        # All Upptime writers share one lock to prevent conflicting git pushes.
        # Keep pending checks when another monitor or maintenance run arrives.
        text = re.sub(r"^  queue: (?:single|max)\n", "", text, flags=re.MULTILINE)
        text, count = re.subn(
            r"(^concurrency:\n  group: [^\n]+\n  cancel-in-progress: false\n)",
            lambda match: match[1] + QUEUE,
            text,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise ValueError(f"{name}: expected one shared, non-cancelling concurrency group")
    if name in {"uptime.yml", "response-time.yml"}:
        text = re.sub(r"^      timezone:.*\n", "", text, flags=re.MULTILINE)
        text, count = re.subn(
            r"(^    - cron: [^\n]+\n)",
            lambda match: match[1] + SCHEDULE_TIMEZONE,
            text,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise ValueError(f"{name}: expected exactly one monitoring schedule")
    if name in MONITORS:
        step = f"      - name: {MONITORS[name]}\n"
        if text.count(step) != 1:
            raise ValueError(f"{name}: expected exactly one monitor step")
        pattern = re.escape(step) + r"(        uses: upptime/uptime-monitor@[^\n]+\n)"
        text, count = re.subn(pattern, lambda match: GATE + step + CONDITION + match[1], text)
        if count != 1:
            raise ValueError(f"{name}: upstream monitor step layout changed")
    if name in UPDATERS:
        step = "      - name: Update template\n"
        if text.count(step) != 1:
            raise ValueError(f"{name}: expected exactly one template update step")
        text = text.replace(step, HOOK + step)
    return text


def main():
    paths = [ROOT / ".github/workflows" / name for name in sorted(WORKFLOWS)]
    # Validate every workflow before modifying any of them.
    updates = [(path, patch_workflow(path.name, path.read_text())) for path in paths]
    for path, text in updates:
        if "--check" in sys.argv:
            if path.read_text() != text:
                raise ValueError(f"{path.name}: monitoring guard is missing")
        else:
            path.write_text(text)
    if "--stage" in sys.argv:
        subprocess.run(["git", "add", "--", *[str(path) for path in paths]], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
