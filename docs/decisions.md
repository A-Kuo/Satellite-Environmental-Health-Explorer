# Decision log

Dated entries for the national rebuild: the decision, the alternatives considered,
the reason, and what should make us revisit it. Newest decisions go at the end of
their section. Three kinds of entry:

- **Decided**: in force.
- **Provisional**: a recommended default is being followed, and the project owner
  has not yet confirmed it.
- **Open**: not decided; a recommended default and a trigger are recorded.

## Decided

### D-001: Neon, as two separate projects (dev and prod) (2026-09-30)
- **Decision:** Postgres + PostGIS on Neon. One Neon project for dev and one for
  prod. Supabase is not used.
- **Alternatives considered:** Supabase (the spec's default); one Neon project with
  `production` and `dev` branches.
- **Reason:** The project owner chose Neon, which the spec already allows (section
  7.6). Separate projects keep prod credentials, limits and billing fully apart
  from dev. Nothing in the schema is provider-specific, so switching costs stay low.
- **Revisit when:** a component needs built-in auth, storage or edge functions, or
  the free-plan limits (D-004, O-001) force a plan change.

### D-002: Schemas `raw`, `core`, `marts`, `research` (2026-09-30)
- **Decision:** Four schemas, and not `raw_*`-prefixed tables inside one schema.
- **Alternatives considered:** prefixes in a single schema.
- **Reason:** Grants are per schema. Keeping `raw` insert-only and `research`
  unreachable from the public API role is a one-line grant per schema.
- **Revisit when:** a provider or tool handles multiple schemas badly.

### D-003: Store geometry in EPSG:4269 (2026-09-30)
- **Decision:** `geometry(MultiPolygon, 4269)`, one declared SRID.
- **Alternatives considered:** EPSG:4326.
- **Reason:** NAD83 is TIGER's native datum and the frozen baseline's `TARGET_CRS`,
  so a regression comparison against the Wisconsin outputs is exact. The NAD83 to
  WGS84 difference is about a metre, irrelevant at tract display scale. Vector
  tiles reproject.
- **Revisit when:** tile tooling requires 4326 inside the database, or non-US
  geographies are added.

### D-004: Compact keys on value rows (2026-09-30)
- **Decision:** `indicator_id` is a `smallint` identity; `indicator_key` (text,
  unique) is the stable public identifier. `geoid` stays text.
- **Alternatives considered:** a text slug as the foreign key; a surrogate integer
  for geographies.
- **Reason:** About 85,000 tracts times dozens of indicators is several million
  value rows, and the free Neon plan showed a 512 MB per-branch limit. Two bytes
  per row instead of a slug adds up. The API and URLs use `indicator_key`.
- **Revisit when:** the first national size measurement (O-001).

### D-005: Percentiles live in their own table (2026-09-30)
- **Decision:** `core.indicator_percentiles`, keyed by value key plus
  `(reference_frame, peer_group)`. `core.indicator_values` holds raw values only.
  This deliberately departs from spec section 6, which put `reference_frame` and
  `percentile_in_frame` on the value row.
- **Alternatives considered:** the spec's columns on `indicator_values`.
- **Reason:** One value can have several frames (national, state, peer group).
  Columns on the value row would duplicate the value per frame and blur the
  natural key. Separating them keeps raw values untouched and lets `concern_percentile`
  (direction-normalized) sit beside `percentile`. A `marts` view can reassemble the
  spec's shape for the API.
- **Revisit when:** the API design shows a real cost to the join, or the spec owner
  prefers the original shape.

### D-006: Plain-SQL migrations with a small runner (2026-09-30)
- **Decision:** `db/migrations/NNN_name.sql` applied by `db/migrate.py`, recorded
  with SHA-256 checksums.
- **Alternatives considered:** Alembic, dbmate, the Supabase CLI.
- **Reason:** Vendor-neutral, one small dependency, and the safety rules that
  matter here are tested: refuses edited, missing or out-of-order files; refuses a
  pooled connection; prod needs `--confirm-prod`.
- **Revisit when:** migrations need rollback scripts or branching workflows.

### D-007: Group roles for access; the analyst role reads `research` (2026-09-30)
- **Decision:** NOLOGIN group roles `ingest_writer`, `api_reader`,
  `analyst_readonly` hold all grants; login roles are created out of band. `raw` is
  insert-only for ingestion. `analyst_readonly` can read `research`.
- **Alternatives considered:** grants directly on login roles; keeping `research`
  away from the analyst role.
- **Reason:** Passwords stay out of git and the SQL is identical in dev and prod.
  The spec lists the analyst role as reading "core and marts" (7.2) but also has
  the Streamlit model-diagnostics page read `research` (4.2); the workbench is
  internal, so it gets `research`. The public API role never does.
- **Revisit when:** a separate research-writer role or a different workbench
  access model is needed.

### D-008: The Wisconsin baseline is frozen (2026-09-30)
- **Decision:** No existing baseline file is modified. New code lives in new paths
  (`src/connectors/`, `db/`, `docs/`, `tests/db/`, `tests/connectors/`).
  `requirements.txt` is untouched; new dependencies go in `requirements-national.txt`
  and `requirements-dev.txt`. Lint and type checks are scoped to the new code.
- **Alternatives considered:** reformatting and refactoring the baseline now.
- **Reason:** It is the reference implementation and the regression test for the
  national pipeline. The baseline suite (55 tests) passed before and after.
- **Revisit when:** the national build reaches parity and Streamlit becomes the
  internal workbench (spec 4.1); migrate baseline modules deliberately then.

### D-009: Environment variables and the `.env/` directory (2026-09-30)
- **Decision:** Variable names are listed in `.env.example`. Local values live in
  `.env/.env`; the whole `.env/` directory is gitignored. Prod credentials live
  only in GitHub Actions `prod` environment secrets, never in a Claude session.
- **Alternatives considered:** a `.env` file at the repo root.
- **Reason:** The baseline already uses `.env/` as a directory holding the GEE
  service-account key, and a file and a directory cannot share a name.
- **Revisit when:** GEE authentication moves to an environment variable.

### D-010: Database tests use throwaway PostGIS, never Neon (2026-09-30)
- **Decision:** DB tests are marked `db` and run against `TEST_DATABASE_URL` (a
  local cluster or the CI service container); each test creates and drops its own
  database. Without the variable they skip.
- **Alternatives considered:** testing against a Neon branch.
- **Reason:** No credentials or network in tests; fast and free; no risk to real
  data. Neon-specific behavior is checked once, by hand, at first apply.
- **Revisit when:** a Neon-specific behavior causes a defect the local run missed.

### D-011: Framework defaults (2026-09-30)
- **Decision:** Coverage may drop at most 10 percentage points against the prior
  release unless an override note is recorded; HTTP minimum interval 1 s, up to 5
  retries, a 30 s pause after 429/406 (capped at 300 s). Fixture mode is refused
  when `APP_ENV=prod`. A payload is registered before it is cleaned, so failures
  leave a provenance row.
- **Alternatives considered:** per-source values only.
- **Reason:** Safe starting points that fail loudly. They are not tuned.
- **Revisit when:** the first real connectors show each source's real limits.

### D-012: Working agreement for this pass (2026-09-30)
- **Decision:** One commit per component on `cursor-interactable-branch`, each with
  code, tests, docs and a "what this does not show" note, and a secret scan before
  the commit. No pull request until asked.
- **Alternatives considered:** one large commit; a pull request per component.
- **Reason:** The working rules ship one component at a time and keep secrets out.
- **Revisit when:** the branch is ready to merge.

## Provisional

### P-001: What "sorted health signals" means (2026-09-30)
- **Decision (recommended default, awaiting confirmation):** Ordered, rankable
  lists of one signal at a time for a chosen geography and period. The sort key is
  chosen by the user; there is no default "worst first" ordering. Each row shows
  value, estimate type, period, margin or interval where available, and source.
  Signals are never blended.
- **Alternatives considered:** a default worst-first ranking (rejected: it implies
  a priority ordering, against section 1.4).
- **Revisit when:** the `/rank` endpoint and the signal panel are designed.

### P-002: County by default, tract on zoom (2026-09-30)
- **Decision (recommended default, awaiting confirmation):** The national view is
  county; tract is the drill-down.
- **Alternatives considered:** tract everywhere.
- **Reason:** Smaller payloads, less false precision, and a database that fits the
  plan tier (O-001).
- **Revisit when:** the size estimate and the tile pipeline (O-005) are done.

## Open

### O-001: Neon plan tier and size (2026-09-30)
- **Recommended default:** keep dev on the free plan with a few states until the
  first national load; measure table sizes then; plan to move prod to a paid tier
  before loading national tract data.
- **Trigger:** any branch above about 400 MB (80% of the observed 512 MB limit), or
  the first national tract load.

### O-002: Backup and retention policy (2026-09-30)
- **Recommended default:** record the real retention for dev and prod in
  `docs/database.md` and the README right after the projects are created. The
  existing free Neon projects showed 6 hours of history retention, which is short.
- **Trigger:** before any prod load.

### O-003: Streamlit workbench hosting and authentication (2026-09-30)
- **Recommended default:** a container behind authentication, using the
  `analyst_login` read-only role.
- **Trigger:** before the first workbench page ships.

### O-004: Where scheduled ingestion runs (2026-09-30)
- **Recommended default:** GitHub Actions only. Add a dedicated worker when GEE batch
  exports or any job outgrows a GitHub-hosted job's runtime limit.
- **Trigger:** the first national GEE batch export.

### O-005: Vector tile generation and hosting (2026-09-30)
- **Recommended default:** prebuilt static tiles per geography vintage (geometry and
  GEOID only), hosted as static files; the database keeps attributes plus county and
  simplified geometry. Neither `tippecanoe` nor `pmtiles` is installed in the current
  environment.
- **Trigger:** before the API and tile component.

### O-006: Which domains must be stable before the research layer (2026-09-30)
- **Recommended default:** foundation, health, and one economic domain, each with at
  least two comparable periods.
- **Trigger:** starting the research layer (spec section 12).

### O-007: The SVI percentile frame (2026-09-30)
- **Question:** README calls the baseline SVI percentile state-relative;
  `methodology.md` and the data dictionary call it national-relative. The Wisconsin
  values (mean 0.4999, quartiles 0.25 and 0.75 over 1,523 tracts) look state-ranked,
  which fits the per-state CDC files the baseline downloads.
- **Recommended default:** in the SVI connector, ingest CDC's national file, store
  the reference frame explicitly on every percentile row, and compute state and
  national percentiles ourselves instead of trusting a published percentile.
- **Trigger:** starting the foundation connectors. The baseline docs are not edited
  (D-008).

### O-008: Wording and labels carried over from the baseline (2026-09-30)
- **Question:** The baseline UI labels values "Relative concern" and "High
  concern", and its `screening_flag` is an AND of two percentiles. Neither is a
  numeric composite, but both read close to the "no priority or harm score" rule
  (section 1.4). Modeled values (PM2.5, cropland and wetland fractions) are marked
  "modeled" only in the methods table, and the tooltip, axis and table columns read
  as plain measurements.
- **Recommended default:** in the national product, label each percentile plainly
  ("percentile, higher = higher value in the concern direction"); show
  `estimate_type` on every value row; do not carry the conjunctive flag over
  without explicit sign-off.
- **Trigger:** the frontend components (map, signal panel, detail drawer).

### O-009: Tables deferred to their domains (2026-09-30)
- **Question:** `crosswalks`, `point_layers`, the `health_signals` view, `research.*`
  tables and materialized views were not created in migration 001.
- **Recommended default:** add each in the migration that ships with the first
  connector or component that needs it; `publish()` will use a `SECURITY DEFINER`
  refresh function for materialized views, since `ingest_writer` does not own them.
- **Trigger:** the PLACES connector (health view), the food domain (crosswalks).
