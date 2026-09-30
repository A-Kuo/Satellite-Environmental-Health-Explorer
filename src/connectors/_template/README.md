# Connector template (`template_demo`)

A copyable skeleton that runs end to end in fixture mode. It is **synthetic**: the
fixture describes no real place or population, and the catalog entry is marked
"Never loaded into prod". The template has no live source, and fixture mode is
refused when `APP_ENV=prod`.

| File | Job |
|---|---|
| `catalog.toml` | indicator definitions (write this first) |
| `client.py` | HTTP client and rate limit for the source |
| `fetch.py` | download, save raw bytes, record the SHA-256 |
| `clean.py` | normalize to the long-format value schema |
| `validate.py` | source-specific gates |
| `load.py` | idempotent upsert (the shared one is usually enough) |
| `fixtures/` | recorded responses for tests (`tract_values.csv`) and the synthetic tracts they refer to |

The fixture deliberately contains the messy cases real sources have: a GEOID that
lost its leading zero (`1001020100`), a float-style GEOID (`55079000400.0`), and a
`-999` missing-value code. See `src/connectors/README.md` for how to turn this
into a real connector.

**What this does not show:** anything about a real data source. It proves the
framework's behavior only.
