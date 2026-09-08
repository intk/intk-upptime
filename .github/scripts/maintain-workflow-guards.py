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
GATE = """      - name: Enforce overnight monitoring window
        id: monitor_window
        run: python3 .github/scripts/monitor-window.py
"""
CONDITION = """        if: steps.monitor_window.outputs.allowed == 'true'
        timeout-minutes: 30
"""
HOOK = """      - name: Preserve monitoring guards during template updates
        run: git config --local core.hooksPath .githooks
"""


def patch_workflow(name, text):
    # Normalize our additions so rerunning this is idempotent.
    text = text.replace(GATE, "").replace(CONDITION, "").replace(HOOK, "")
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
    paths = [ROOT / ".github/workflows" / name for name in sorted(MONITORS.keys() | UPDATERS)]
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
