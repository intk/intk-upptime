"""Check only from 06:00 until midnight in Amsterdam, even after queue delays."""

from datetime import datetime, timezone, timedelta
import os
from zoneinfo import ZoneInfo

MONITOR_TIMEZONE = ZoneInfo("Europe/Amsterdam")


def timeout_minutes(now):
    if now.tzinfo is None:
        raise ValueError("The monitoring clock must include a timezone")
    local = now.astimezone(MONITOR_TIMEZONE)
    if local.hour < 6:
        return 0
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    # GitHub step timeouts must be whole minutes. Keep one minute for step
    # startup/cancellation, instead of losing the final half-hour of monitoring.
    remaining = int((midnight - local).total_seconds() // 60) - 1
    return max(0, min(30, remaining))


def can_check(now):
    return timeout_minutes(now) > 0


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    timeout = timeout_minutes(now)
    allowed = timeout > 0
    message = (
        f"Uptime checks enabled (06:00–24:00 Europe/Amsterdam; timeout {timeout} minutes)."
        if allowed
        else "Skipping checks: outside 06:00–24:00 Europe/Amsterdam or too close to midnight."
    )
    print(f"{now.isoformat()}: {message}")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"allowed={str(allowed).lower()}\n")
        # A skipped step still needs a valid positive timeout expression.
        output.write(f"timeout_minutes={max(1, timeout)}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(message + "\n")
