# What this does not show

Limits of each component of the national rebuild, updated as each one ships.
The Wisconsin/Minnesota baseline keeps its own list in `methodology.md`
("What this project does not show").

## Connector framework

- **It proves the framework, not any dataset.** The end-to-end tests run a
  synthetic template against a local PostGIS. No real source (Census, CDC, USDA,
  GEE) has been connected, so nothing here says a real release loads, or that its
  quirks are handled.
- **Gates catch structural and range problems, not wrong data.** A value inside
  its plausible range, present in the right geography, with the right period can
  still be a bad estimate. Passing every gate means "well-formed", not "correct".
- **Plausible ranges are declared, not measured.** Each source's range is a human
  judgment in its catalog and is only as good as that judgment.
- **The coverage-drop gate compares against what is already loaded.** On a first
  load there is nothing to compare with, so it passes by design. A `10%` default
  threshold is a starting point, not a validated tolerance.
- **Sentinel codes are declared per source, never detected.** A code the source
  documents but the connector forgets to declare would survive as a real value;
  only the `sentinels_gone` gate for the codes that were declared would notice.
- **A failed fetch leaves no ingest-log row.** Registration happens after the raw
  payload is saved, so a request that never returned data is reported by the
  exception, not by the log.
- **Polite-client behavior is tested with a fake clock and transport.** Real APIs'
  rate limits, `Retry-After` conventions and outages are not exercised, and
  live requests have never been made.
- **One worker per source relies on a direct Postgres connection.** The lock does
  not work through a transaction-pooled connection, so the framework refuses one.
- **Provenance points at the payload that last changed a value.** Re-running an
  unchanged release logs a new payload row but leaves each value's
  `ingest_run_id` on the run that first set it.
- **Redaction is name-based.** It masks credential-looking parameter names and
  `name=value` text. A secret embedded under an innocuous name would not be
  recognized.

## Database schema and migrations

- **The schema holds no data yet.** Passing schema tests show that malformed
  GEOIDs, duplicate keys, missing vintages and out-of-range percentiles are
  rejected. They say nothing about whether any dataset, once loaded, is correct.
  That is the job of each connector's validation gates.
- **Constraints are not scientific validation.** A value inside a catalog's
  plausible range can still be wrong, and a plausible range is a sanity check, not
  a measurement of quality.
- **Nothing here has run against Neon yet.** The migrations were tested on a
  local PostgreSQL 16 with PostGIS 3.4, and CI uses a PostGIS container. Neon's
  Postgres version, extension versions and free-plan limits are unverified until
  the first apply.
- **No size or performance claim.** Table sizes at national scale, query latency
  and index effectiveness are unmeasured. The 512 MB free-plan limit is an
  observation from other projects, not a guarantee for the new ones.
- **Percentiles can go stale.** They are derived rows and are not recomputed
  automatically when a value is revised.
- **Roles are tested as group roles.** The login-role script was exercised on a
  local cluster only; it does not prove a provider's console or API behaves the
  same way.
- **Access control is one layer.** The database refuses reads outside `marts` for
  the API role, but the API and its input validation do not exist yet.

## Repo hygiene and tooling

- **The secret scan is not proof of absence.** `detect-secrets` is pattern and
  entropy based and runs on tracked files. A separate one-time regex check of git
  history (private-key, cloud-key and token patterns) found nothing on
  2026-09-30, but that was not a full-history scan by a dedicated tool.
- **Ignoring a file does not remove it from history.** `.claude/launch.json` is
  now untracked, but earlier commits still contain it. It holds no secret.
- **Lint and type checks cover only the national-rebuild code.** The frozen
  Wisconsin baseline (`src/*.py`, `app/`, existing tests) is not linted or
  formatted, so "lint clean" says nothing about it.
- **Pre-commit hooks are opt-in per clone** (`pre-commit install`). CI repeats the
  secret scan and lint on every push and pull request, and that is the backstop.
- **CI shows the code passes on a clean Linux runner, not that any dataset is
  correct.** Data validity is the job of each connector's validation gates.
