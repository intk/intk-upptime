# Monitoring schedule

INTK, Bonnefanten, and Het Markiezenhof are monitored during the Amsterdam daytime
window, 06:00–24:00, throughout the week. `Europe/Amsterdam` follows daylight saving
time automatically. The runtime guard checks the actual start time, including
manual or externally dispatched runs, so delayed jobs skip overnight checks.

The GitHub schedule requests an uptime check at minutes 02, 07, …, 57 of every hour
from 06 through 23. The offset avoids the busiest minute of the hour. Response-time
measurements are scheduled at 12:17 Amsterdam time. Other maintenance workflows can
run overnight because they do not probe the sites.

Monitoring steps have a maximum timeout of 30 minutes, reduced near midnight.
They reserve one minute for startup/cancellation and skip starts after 23:58 to
avoid allowing retries into the overnight window.

## Scheduling reliability

GitHub's native cron is best effort: events can be delayed or dropped. On
5 October 2026 the consecutive daytime uptime runs started at 15:55 and 23:24
Amsterdam time, although each run finished in under 30 seconds. Moving the cron
offset reduces contention but does not guarantee five-minute monitoring.

For dependable triggering, configure an always-on external scheduler with:

- Schedule: `*/5 6-23 * * *`, timezone `Europe/Amsterdam`.
- Method: `POST`.
- URL: `https://api.github.com/repos/intk/intk-upptime/actions/workflows/uptime.yml/dispatches`.
- Headers: `Accept: application/vnd.github+json`, `Authorization: Bearer <token>`,
  `Content-Type: application/json`, `X-GitHub-Api-Version: 2022-11-28`.
- JSON body: `{"ref":"master"}`.
- Expected result: HTTP 204. Report failed requests through the scheduler's own
  failure notification mechanism.

Use a dedicated fine-grained GitHub token scoped to this repository with Actions
write permission, stored only in the scheduler's secret store. Never commit a
token or put it in the URL. The external scheduler has **not yet been installed**.
Dispatching bypasses the cron delays but still depends on GitHub runner availability;
check the completed `Check endpoint status` step, not only the dispatch response.

## Template updates and verification

`.upptimerc.yml` owns the cron expressions. The pre-commit hook used by Setup CI and
Update Template CI restores the timezone, runtime gate, and timeout expression on
regenerated workflows. Keep the hook when updating Upptime.

Run `python3 .github/scripts/test-monitoring.py` and
`python3 .github/scripts/maintain-workflow-guards.py --check` to verify daylight
saving boundaries and regeneration behavior.

Sources: [GitHub scheduling behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
and [Upptime workflow triggers](https://upptime.js.org/docs/triggers/).
