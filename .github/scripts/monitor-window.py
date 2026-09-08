"""Enforce the existing overnight exclusion using the actual check start time."""

from datetime import datetime, timezone
import os


def can_check(now):
    # Every monitor step is limited to 30 minutes. Do not start a check whose
    # retries could cross into the existing 01:00–06:00 UTC exclusion.
    utc = now.astimezone(timezone.utc)
    minute = utc.hour * 60 + utc.minute
    return not 30 <= minute < 360


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    allowed = can_check(now)
    message = (
        "Uptime checks enabled."
        if allowed
        else "Skipping checks: overnight exclusion (01:00–06:00 UTC), including a 30-minute retry buffer."
    )
    print(f"{now.isoformat()}: {message}")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"allowed={str(allowed).lower()}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(message + "\n")
