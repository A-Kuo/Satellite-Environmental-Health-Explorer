-- 001_core_schema.sql
-- Extensions, schemas and the core tables of the national rebuild.
-- Plain Postgres + PostGIS + pg_trgm only: no Neon- or Supabase-specific SQL,
-- so the same file applies to either provider and to a local PostGIS.
--
-- Deliberate deviation from the design spec (docs/decisions.md, D-005):
-- percentiles live in core.indicator_percentiles, keyed by reference frame,
-- and NOT as columns on core.indicator_values. One value can have several
-- frames (national, state, peer group); columns on the value row would
-- duplicate value rows and blur the natural key. Raw values stay untouched.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- raw: immutable landing tables; core: normalized data; marts: API-facing views;
-- research: model registry and forecasts (never exposed publicly).
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS research;

-- ---------------------------------------------------------------------------
-- core.ingest_log: one row per fetched payload (URL + params), updated in place
-- as the payload moves through fetched -> cleaned -> validated -> loaded ->
-- published (or failed). Every value row points at the payload it came from.
-- ---------------------------------------------------------------------------
CREATE TABLE core.ingest_log (
    ingest_run_id  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source         text        NOT NULL,
    url            text        NOT NULL,
    params         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    fetched_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    sha256         char(64),
    row_count      bigint,
    bytes          bigint,
    geo_vintage    smallint,
    status         text        NOT NULL,
    is_fixture     boolean     NOT NULL DEFAULT false,
    notes          text,
    CONSTRAINT ingest_log_status_ck CHECK (
        status IN ('fetched', 'cleaned', 'validated', 'loaded', 'published', 'failed')),
    CONSTRAINT ingest_log_sha256_ck CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ingest_log_counts_ck CHECK (
        (row_count IS NULL OR row_count >= 0) AND (bytes IS NULL OR bytes >= 0)),
    CONSTRAINT ingest_log_source_ck CHECK (source <> '' AND url <> '')
);
CREATE INDEX ingest_log_source_fetched_ix ON core.ingest_log (source, fetched_at DESC);
CREATE INDEX ingest_log_sha256_ix ON core.ingest_log (sha256);

COMMENT ON TABLE core.ingest_log IS
    'One row per fetched payload. ingest_run_id is the provenance key referenced by value rows. is_fixture marks recorded-fixture loads, which must never be published as real data.';

-- ---------------------------------------------------------------------------
-- core.geographies: boundaries by level and vintage (2010 and 2020 tracts are
-- different geographies and must never be silently mixed).
-- ---------------------------------------------------------------------------
CREATE TABLE core.geographies (
    geoid         text     NOT NULL,
    geo_level     text     NOT NULL,
    geo_vintage   smallint NOT NULL,
    name          text     NOT NULL,
    state_fips    char(2),
    county_fips   char(5),
    geom          geometry(MultiPolygon, 4269),
    land_area_m2  bigint,
    CONSTRAINT geographies_pk PRIMARY KEY (geoid, geo_vintage),
    CONSTRAINT geographies_level_ck CHECK (geo_level IN ('state', 'county', 'tract', 'zcta')),
    CONSTRAINT geographies_vintage_ck CHECK (geo_vintage BETWEEN 1990 AND 2100),
    -- Zero-padded string GEOIDs: state 2, county 5, tract 11, ZCTA 5 digits.
    CONSTRAINT geographies_geoid_ck CHECK (
        (geo_level = 'state' AND geoid ~ '^[0-9]{2}$')
        OR (geo_level IN ('county', 'zcta') AND geoid ~ '^[0-9]{5}$')
        OR (geo_level = 'tract' AND geoid ~ '^[0-9]{11}$')),
    -- The FIPS columns must agree with the GEOID. ZCTAs cross state lines, so
    -- they carry neither.
    CONSTRAINT geographies_hierarchy_ck CHECK (
        CASE geo_level
            WHEN 'state'  THEN state_fips = geoid AND county_fips IS NULL
            WHEN 'county' THEN state_fips = left(geoid, 2) AND county_fips = geoid
            WHEN 'tract'  THEN state_fips = left(geoid, 2) AND county_fips = left(geoid, 5)
            WHEN 'zcta'   THEN state_fips IS NULL AND county_fips IS NULL
        END),
    CONSTRAINT geographies_land_area_ck CHECK (land_area_m2 IS NULL OR land_area_m2 >= 0)
);
CREATE INDEX geographies_geom_gix ON core.geographies USING gist (geom);
CREATE INDEX geographies_name_trgm_ix ON core.geographies USING gin (name gin_trgm_ops);
CREATE INDEX geographies_level_ix ON core.geographies (geo_level, geo_vintage, state_fips);
CREATE INDEX geographies_county_ix ON core.geographies (county_fips);

COMMENT ON TABLE core.geographies IS
    'Boundaries by (geoid, geo_vintage). Geometry is stored in one declared SRID, EPSG:4269 (NAD83, TIGER native); vector tiles reproject. geom is NULL until a boundary is loaded.';

-- ---------------------------------------------------------------------------
-- core.indicator_catalog: one row per indicator. The catalog carries the
-- source, license, estimate type and plausible range that the validation gates
-- read; a value cannot be loaded without an entry here.
-- ---------------------------------------------------------------------------
CREATE TABLE core.indicator_catalog (
    indicator_id        smallint         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    indicator_key       text             NOT NULL UNIQUE,
    domain              text             NOT NULL,
    name                text             NOT NULL,
    description         text             NOT NULL,
    unit                text             NOT NULL,
    direction           text             NOT NULL,
    estimate_type       text             NOT NULL,
    native_geo_level    text             NOT NULL,
    native_geo_vintage  smallint         NOT NULL,
    refresh_cadence     text             NOT NULL,
    source_name         text             NOT NULL,
    source_url          text             NOT NULL,
    license             text             NOT NULL,
    notes               text,
    plausible_min       double precision,
    plausible_max       double precision,
    CONSTRAINT catalog_key_format_ck CHECK (indicator_key ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$'),
    -- A composite score must not be registrable as an indicator.
    CONSTRAINT catalog_no_composite_ck CHECK (
        indicator_key !~ '(risk|priority|harm|inequality)_score'),
    CONSTRAINT catalog_domain_ck CHECK (
        domain IN ('health', 'environment', 'economic', 'education', 'food', 'policy')),
    CONSTRAINT catalog_direction_ck CHECK (
        direction IN ('higher_is_concern', 'higher_is_protective', 'neutral')),
    CONSTRAINT catalog_estimate_type_ck CHECK (
        estimate_type IN ('observed', 'survey', 'model_based', 'derived')),
    CONSTRAINT catalog_native_level_ck CHECK (
        native_geo_level IN ('state', 'county', 'tract', 'zcta')),
    CONSTRAINT catalog_vintage_ck CHECK (native_geo_vintage BETWEEN 1990 AND 2100),
    CONSTRAINT catalog_cadence_ck CHECK (
        refresh_cadence IN ('monthly', 'quarterly', 'annual', 'biennial', 'irregular', 'one_time')),
    CONSTRAINT catalog_source_url_ck CHECK (source_url ~ '^https?://'),
    CONSTRAINT catalog_license_ck CHECK (btrim(license) <> ''),
    CONSTRAINT catalog_text_ck CHECK (
        btrim(name) <> '' AND btrim(description) <> '' AND btrim(unit) <> ''
        AND btrim(source_name) <> ''),
    CONSTRAINT catalog_range_ck CHECK (
        plausible_min IS NULL OR plausible_max IS NULL OR plausible_min <= plausible_max)
);

COMMENT ON TABLE core.indicator_catalog IS
    'Indicator definitions. indicator_id is a compact surrogate key used by value rows; indicator_key is the stable public identifier used by the API.';
COMMENT ON COLUMN core.indicator_catalog.direction IS
    'higher_is_concern | higher_is_protective | neutral. Used only to derive concern_percentile; raw values are never inverted.';
COMMENT ON COLUMN core.indicator_catalog.estimate_type IS
    'observed | survey | model_based | derived. Model-based estimates (e.g. CDC PLACES) are never presented as direct measurements.';

-- ---------------------------------------------------------------------------
-- core.indicator_values: long-format raw values. The primary key is the natural
-- key, so re-running a connector upserts and never duplicates.
-- ---------------------------------------------------------------------------
CREATE TABLE core.indicator_values (
    geoid           text             NOT NULL,
    geo_vintage     smallint         NOT NULL,
    indicator_id    smallint         NOT NULL REFERENCES core.indicator_catalog (indicator_id),
    period_start    date             NOT NULL,
    period_end      date             NOT NULL,
    value           double precision,
    moe_or_ci_low   double precision,
    moe_or_ci_high  double precision,
    coverage_flag   text             NOT NULL DEFAULT 'ok',
    ingest_run_id   uuid             NOT NULL REFERENCES core.ingest_log (ingest_run_id),
    CONSTRAINT indicator_values_pk PRIMARY KEY
        (geoid, geo_vintage, indicator_id, period_start, period_end),
    -- The vintage must exist in geographies before a value can reference it.
    CONSTRAINT indicator_values_geo_fk FOREIGN KEY (geoid, geo_vintage)
        REFERENCES core.geographies (geoid, geo_vintage),
    CONSTRAINT indicator_values_period_ck CHECK (period_end >= period_start),
    CONSTRAINT indicator_values_coverage_ck CHECK (
        coverage_flag IN ('ok', 'suppressed', 'partial_coverage', 'imputed', 'no_data')),
    -- A row flagged ok must carry a value; missing values say why.
    CONSTRAINT indicator_values_ok_has_value_ck CHECK (value IS NOT NULL OR coverage_flag <> 'ok'),
    CONSTRAINT indicator_values_interval_ck CHECK (
        moe_or_ci_low IS NULL OR moe_or_ci_high IS NULL OR moe_or_ci_low <= moe_or_ci_high)
);
-- The primary key already leads with geoid, so it serves geoid lookups; this
-- index serves "one indicator, one vintage, one period" scans for the API.
CREATE INDEX indicator_values_indicator_ix
    ON core.indicator_values (indicator_id, geo_vintage, period_end);

COMMENT ON TABLE core.indicator_values IS
    'Raw values in long format, exactly as published. Never inverted or rescaled; direction normalization lives in core.indicator_percentiles.';
COMMENT ON COLUMN core.indicator_values.moe_or_ci_low IS
    'Lower bound of the published margin of error or confidence interval, as an absolute value (value - MOE for margins).';

-- ---------------------------------------------------------------------------
-- core.indicator_percentiles: derived, one row per (value, reference frame).
-- Percentiles are stored per frame and never mixed in one column.
-- ---------------------------------------------------------------------------
CREATE TABLE core.indicator_percentiles (
    geoid               text             NOT NULL,
    geo_vintage         smallint         NOT NULL,
    indicator_id        smallint         NOT NULL,
    period_start        date             NOT NULL,
    period_end          date             NOT NULL,
    reference_frame     text             NOT NULL,
    peer_group          text             NOT NULL DEFAULT '',
    percentile          double precision NOT NULL,
    concern_percentile  double precision,
    n_in_frame          integer          NOT NULL,
    rank_method         text             NOT NULL DEFAULT 'average',
    ingest_run_id       uuid             NOT NULL REFERENCES core.ingest_log (ingest_run_id),
    CONSTRAINT indicator_percentiles_pk PRIMARY KEY
        (geoid, geo_vintage, indicator_id, period_start, period_end, reference_frame, peer_group),
    CONSTRAINT indicator_percentiles_value_fk
        FOREIGN KEY (geoid, geo_vintage, indicator_id, period_start, period_end)
        REFERENCES core.indicator_values (geoid, geo_vintage, indicator_id, period_start, period_end),
    CONSTRAINT indicator_percentiles_frame_ck CHECK (
        reference_frame IN ('national', 'state', 'peer_group')),
    -- peer_group is meaningful only for the peer_group frame.
    CONSTRAINT indicator_percentiles_peer_ck CHECK (
        (reference_frame = 'peer_group') = (peer_group <> '')),
    CONSTRAINT indicator_percentiles_range_ck CHECK (
        percentile BETWEEN 0 AND 1
        AND (concern_percentile IS NULL OR concern_percentile BETWEEN 0 AND 1)),
    CONSTRAINT indicator_percentiles_n_ck CHECK (n_in_frame >= 1)
);
CREATE INDEX indicator_percentiles_indicator_ix
    ON core.indicator_percentiles (indicator_id, geo_vintage, period_end, reference_frame);

COMMENT ON TABLE core.indicator_percentiles IS
    'Percentile of a value within one reference frame. concern_percentile applies the catalog direction so higher always means higher concern for screening views (NULL for neutral indicators). Recompute after a value revision; stale rows are not detected automatically.';
