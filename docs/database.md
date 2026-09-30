# Database

Postgres + PostGIS on **Neon**, as two separate projects (dev and prod). The
schema is plain SQL under `db/migrations/`, applied by `db/migrate.py`. Nothing
provider-specific is used, so the same files apply to Neon, Supabase or a local
PostGIS. Design decisions and the one deliberate deviation from the spec are in
[decisions.md](decisions.md).

## Schemas and tables

| Schema | Holds | Exposed to |
|---|---|---|
| `raw` | Immutable landing tables (none yet; one per source when a connector needs it) | `ingest_writer` (insert-only) |
| `core` | Normalized data (below) | `ingest_writer` (read/write), `analyst_readonly` (read) |
| `marts` | API-facing views and materialized views (none yet) | `api_reader`, `analyst_readonly` |
| `research` | Model registry and forecasts (none yet) | `analyst_readonly` only |

| `core` table | One row per | Natural key |
|---|---|---|
| `geographies` | boundary by level and vintage | `(geoid, geo_vintage)` |
| `indicator_catalog` | indicator definition | `indicator_key` (compact `indicator_id smallint` is the join key) |
| `indicator_values` | raw value | `(geoid, geo_vintage, indicator_id, period_start, period_end)` |
| `indicator_percentiles` | value within one reference frame | value key + `(reference_frame, peer_group)` |
| `ingest_log` | fetched payload | `ingest_run_id` (uuid) |

Not created yet, because their data domains have not shipped: `crosswalks`,
`point_layers`, the `health_signals` view, `research.*` tables and any
materialized view.

### Rules the database enforces

- **GEOIDs** are zero-padded strings of the right length per level (state 2,
  county 5, tract 11, ZCTA 5), and `state_fips` / `county_fips` must agree with
  the GEOID. ZCTAs cross state lines and carry neither.
- **Vintage is part of identity.** A 2010 and a 2020 tract with the same GEOID are
  two geographies. A value must reference a geography vintage that exists.
- **One SRID.** Geometry is `geometry(MultiPolygon, 4269)` (NAD83, TIGER native,
  matching the Wisconsin baseline); vector tiles reproject. PostGIS promotes a
  plain Polygon to a MultiPolygon on insert and rejects other types and other
  SRIDs. `geom` is nullable until a boundary is loaded.
- **The natural key is the primary key**, so a re-run upserts and never
  duplicates. There is no separate geoid index: the key leads with `geoid`.
- **A row flagged `ok` must have a value.** Missing values say why
  (`suppressed`, `partial_coverage`, `imputed`, `no_data`).
- **Every value points at its payload** through `ingest_run_id`. `ingest_log`
  has one row per fetched payload (a URL with its parameters), updated through
  `fetched, cleaned, validated, loaded, published` or `failed`. `is_fixture`
  marks recorded-fixture loads, which must never be published as real data.
- **The catalog carries the metadata the gates read**: source URL (`http(s)`),
  a non-blank license, estimate type, direction, native geography and vintage,
  cadence and plausible range. An indicator key naming a composite score cannot
  be registered.

### Percentiles are a separate table (deviation from the spec)

The spec put `reference_frame` and `percentile_in_frame` on `indicator_values`.
Here they live in `core.indicator_percentiles`, because one value can have
several frames (national, state, peer group). Columns on the value row would
duplicate the value and make the natural key ambiguous. Raw values stay untouched;
`concern_percentile` applies the catalog `direction` (higher always means higher
concern; `NULL` for neutral indicators). A `marts` view can reassemble the spec's
shape when the API needs it. Percentiles are not recomputed automatically when a
value is revised.

## Roles

Three NOLOGIN **group** roles hold every grant (migration `002`). Login roles are
created out of band, so passwords never enter version control.

| Group role | Reads | Writes | Used by |
|---|---|---|---|
| `ingest_writer` | `raw`, `core` | `raw` insert-only, `core` insert/update/delete | scheduled ingestion |
| `api_reader` | `marts` only | nothing | the public API |
| `analyst_readonly` | `core`, `marts`, `research` | nothing | Streamlit workbench |

Nothing is granted to `PUBLIC`. `research` is readable by `analyst_readonly`
because the workbench's model-diagnostics page reads it (spec section 4.2); it is
never readable by the public API role. Default privileges apply the same grants to
objects created later by the migration owner.

Create the logins once per environment (see the header of
`db/ops/create_login_roles.sql`; it refuses to run if a password variable is unset).

## Connection strings and environment variables

Names only; values live in `.env/.env`, the cloud environment's secret settings,
or GitHub environment secrets. Never in chat, git or an issue.

| Variable | Connection | Used by |
|---|---|---|
| `DATABASE_URL_MIGRATE` | direct, owner role | `db/migrate.py` |
| `DATABASE_URL_INGEST` | direct, `ingest_login` | ingestion jobs |
| `DATABASE_URL_API` | pooled, `api_login` | FastAPI |
| `DATABASE_URL_ANALYST` | pooled, `analyst_login` | Streamlit |
| `TEST_DATABASE_URL` | throwaway local/CI PostGIS | DB tests only |

Neon's pooled host contains `-pooler`. Migrations refuse a pooled host: they use
session-level advisory locks. Clients on a pooled connection must not rely on
server-side prepared statements (set `prepare_threshold=None` in psycopg).
Prod credentials belong only in GitHub Actions `prod` environment secrets.

## Applying migrations

```bash
APP_ENV=dev  python -m db.migrate --dry-run       # list pending, change nothing
APP_ENV=dev  python -m db.migrate                 # apply
APP_ENV=prod python -m db.migrate --confirm-prod  # prod needs the flag to apply
```

Files are applied in order, one transaction each, and recorded with a SHA-256 in
`public.schema_migrations`. The runner refuses if an applied file was edited, an
applied file is missing, or a new file is older than the newest applied one. Line
endings are normalized before hashing, so a Windows checkout does not change a
checksum. **Never edit an applied migration; add a new one.**

## Setting up a Neon project

1. Create the project (suggested region `aws-us-east-1`, near Vercel's default
   function region). Do this twice, for dev and prod.
2. Confirm `postgis` and `pg_trgm` are offered:
   `SELECT name FROM pg_available_extensions WHERE name IN ('postgis','pg_trgm');`
3. Copy the **direct** connection string into `DATABASE_URL_MIGRATE` (dev only in
   the cloud session; prod only in GitHub).
4. `--dry-run`, then apply, then re-run (must report `none (up to date)`).
5. Create the login roles and store their strings as secrets.
6. Record the size baseline: `SELECT pg_size_pretty(pg_database_size(current_database()));`

## Limits to watch

- **Storage.** The free plan showed a **512 MB logical size limit per branch** on
  the existing Neon projects in this organization. A national tract load (about
  85,000 tracts of geometry plus several million value rows with indexes) will
  probably exceed it. Value rows use compact keys (`smallint` indicator id) for
  this reason. Estimate table sizes after the first load; the plan tier is an open
  decision.
- **Backups and retention.** Not yet recorded for these projects. The existing free
  Neon projects showed 6 hours of history retention. Confirm the real figure for
  dev and prod after creation and record it here and in the README.
- **Publishing.** Refreshing a materialized view requires owning it, which
  `ingest_writer` does not. When the first mart ships, `publish()` will call a
  `SECURITY DEFINER` refresh function instead of granting ownership.
- **Cold starts.** Neon computes can scale to zero; API clients must tolerate a
  slow first connection.

## Testing

DB tests are marked `db` and skipped unless `TEST_DATABASE_URL` points at a
throwaway PostGIS server with a superuser (each test creates and drops its own
database). CI provides one as a service container. Locally:

```bash
export TEST_DATABASE_URL="host=/var/run/postgresql dbname=postgres"   # local cluster
python -m pytest tests/db tests/test_forbidden_names.py
```
