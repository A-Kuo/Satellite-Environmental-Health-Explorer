# What this does not show

Limits of each component of the national rebuild, updated as each one ships.
The Wisconsin/Minnesota baseline keeps its own list in `methodology.md`
("What this project does not show").

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
