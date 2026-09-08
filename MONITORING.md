# Overnight monitoring exclusion

The uptime schedule already excludes 01:00–06:00 UTC. GitHub can start a
scheduled job late: incident #1724 started checking INTK at 01:06 UTC despite
that exclusion, timed out nine times, and stayed open until the next run at
10:49 UTC. Its reported duration does not establish a continuous outage.

The uptime, response-time and setup workflows now check the actual UTC time
immediately before probing sites. They skip probes from 00:30 through 05:59
UTC. The extra 30 minutes prevent retries from crossing into the exclusion;
each monitoring step is limited to 30 minutes. Manual runs respect the same
window. Existing HTTP failure detection and retries continue outside it.
Skipped checks do not mark sites healthy or rewrite incident history.

The exclusion remains in UTC as in the original schedule: 01:00–06:00 UTC
is 03:00–08:00 in Amsterdam during summer and 02:00–07:00 during winter.

## Automatic template updates

Upptime regenerates workflow files in Setup CI and Update Template CI. Both
install `.githooks/pre-commit` in their temporary runner checkout. Before the
generated files are committed, the hook reapplies the time checks and its own
installation steps. Upstream action versions and secret allowlists continue
to update. The hook aborts a commit if the expected step structure changes.
No repository hooks are installed on contributors' computers automatically.

After editing monitoring rules, run:

```sh
python3 .github/scripts/maintain-workflow-guards.py
python3 .github/scripts/test-monitoring.py
python3 .github/scripts/maintain-workflow-guards.py --check
```

Change the UTC window in `monitor-window.py` and its tests if overnight
monitoring requirements change. Keep its retry buffer consistent with the
step timeout in `maintain-workflow-guards.py`.
