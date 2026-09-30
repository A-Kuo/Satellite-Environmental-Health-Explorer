-- 002_roles_and_grants.sql
-- Least-privilege access model. Three NOLOGIN *group* roles carry every grant;
-- LOGIN roles (with passwords) are created out of band by
-- db/ops/create_login_roles.sql and made members of one group. That keeps
-- passwords out of version control and the SQL identical in dev and prod.
--
--   ingest_writer     scheduled ingestion. Insert-only on raw (raw payloads are
--                     immutable); read/write on core. No access to research.
--   api_reader        the public API. Reads marts ONLY: raw, core and research
--                     are not exposed.
--   analyst_readonly  internal Streamlit workbench. Reads core, marts and
--                     research (the model-diagnostics page). Never writes.

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['ingest_writer', 'api_reader', 'analyst_readonly'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
END
$$;

-- Nothing is reachable through PUBLIC. The public schema still needs USAGE for
-- the roles below so PostGIS types and functions resolve.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO ingest_writer, api_reader, analyst_readonly;

-- ingest_writer -------------------------------------------------------------
GRANT USAGE ON SCHEMA raw, core TO ingest_writer;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA raw TO ingest_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core TO ingest_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA raw, core TO ingest_writer;

-- api_reader ----------------------------------------------------------------
GRANT USAGE ON SCHEMA marts TO api_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA marts TO api_reader;

-- analyst_readonly ----------------------------------------------------------
GRANT USAGE ON SCHEMA core, marts, research TO analyst_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA core, marts, research TO analyst_readonly;

-- Objects created later by this migration owner inherit the same grants, so a
-- new table or materialized view is never silently unreadable or over-exposed.
ALTER DEFAULT PRIVILEGES IN SCHEMA raw
    GRANT SELECT, INSERT ON TABLES TO ingest_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA core
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ingest_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA core
    GRANT USAGE, SELECT ON SEQUENCES TO ingest_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA raw
    GRANT USAGE, SELECT ON SEQUENCES TO ingest_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA core
    GRANT SELECT ON TABLES TO analyst_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA marts
    GRANT SELECT ON TABLES TO api_reader, analyst_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA research
    GRANT SELECT ON TABLES TO analyst_readonly;
