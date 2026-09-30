# Connector framework

Every data source (Census, CDC PLACES, USDA, GEE exports, ...) is a connector
with the same six stages, so no source can skip provenance, validation or
idempotency. Nothing here imports from the frozen Wisconsin pipeline.

```
fetch()     download / call the API; raw bytes are saved once, immutably
register()  core.ingest_log row: URL, params (redacted), SHA-256, size
clean()     normalize to the long-format value schema
validate()  run the gates; fail loudly, listing every failure at once
load()      idempotent upsert into core tables
publish()   refresh marts (a hook; a no-op until the first mart exists)
```

`Connector.run(conn)` in `base.py` runs them in order for every payload. A
concrete connector implements `fetch` and `clean`, and optionally
`validate_domain` (source-specific gates) and `publish`.

## What the framework guarantees

| Guarantee | How |
|---|---|
| Raw data is immutable and re-cleanable | `raw_store.py`: content-addressed, write-once, read-only files; a repeat is a no-op; tampering is detected |
| Unchanged releases are not re-downloaded | conditional GET (ETag / Last-Modified) via `SourceClient.fetch_to_store` |
| Truthful, stable identity | User-Agent names the project and `CONNECTOR_CONTACT`; never spoofed |
| Polite to public APIs | minimum request interval; exponential backoff with full jitter; a long pause (honoring `Retry-After`) after 429/406 |
| One worker per source | Postgres advisory lock (`lock.py`); a second run is refused |
| Every value has provenance | `ingest_run_id` -> `core.ingest_log`; status advances one step at a time |
| Credentials never logged | URLs, params and error text are redacted before storage (`ingest_log.py`) |
| Loads are idempotent | staged with COPY, upserted on the natural key, written only when a value changed |
| All or nothing | gates run before load; a failed run rolls back and is recorded as `failed` |
| Fixtures never reach prod | fixture mode is refused when `APP_ENV=prod`; log rows carry `is_fixture` |

## The validation gates (`gates.py`)

Each gate is a pure function returning a `GateResult`. `enforce` raises one
`GateFailure` listing every failure.

- structure: not empty, required columns, no composite-score columns
- identifiers: GEOID format per level, known state FIPS prefix (50 states, DC,
  territories), no duplicates on the natural key
- geography: vintage recorded and loaded, every `(geoid, vintage)` present in
  `core.geographies` (join audit), CRS known and equal to the declared SRID
- values: within the catalog's plausible range, no surviving sentinel codes,
  coverage flags consistent (an `ok` row has a value)
- time: periods present and ordered, and periods and vintages never silently mixed
- catalog: every indicator has an entry with a source URL and a license
- coverage: per-state coverage compared with the prior release; a sharp drop fails
  unless a non-blank override note is given, and the override is stored in the log

## Adding a connector

1. Copy `_template/` to `src/connectors/<source>/` (lower-case name, underscores).
2. **Write `catalog.toml` first**: unit, direction, estimate type, native
   geography and vintage, cadence, source URL, license, plausible range. Decide the
   reference frames and record known limitations before any code.
3. `client.py`: build a `SourceClient` with the source's documented rate limit; read
   any key from an environment variable named for the source (never a literal).
4. `fetch.py`: save raw bytes with `fetch_to_store`. Use a `request_key` without
   credentials.
5. `clean.py`: read as text, `normalize_geoid`, convert declared sentinels with
   `replace_sentinels` (declare them per source; do not guess), flag gaps with
   `flag_missing_values`, and return exactly `gates.VALUE_COLUMNS`.
6. `validate.py`: add source-specific gates.
7. Record a small **fixture** of the real response under `fixtures/` and write
   contract tests against it. No test may touch the network.
8. Write the connector's `README.md`: source, license, cadence, quirks, and a
   "what this does not show" list. Then add it to `docs/what_this_does_not_show.md`.

Geographies must be loaded before values (a value references its geography
vintage). Boundaries come from the foundation connectors.

## Running

```python
from src.connectors import warehouse
from src.connectors.raw_store import RawStore

conn = warehouse.connect("DATABASE_URL_INGEST")     # direct connection, ingest_login
report = MyConnector(store=RawStore()).run(conn)
```

Live runs need `CONNECTOR_CONTACT`. Heavy or long-running jobs run on scheduled
workers, never in a serverless request handler.
