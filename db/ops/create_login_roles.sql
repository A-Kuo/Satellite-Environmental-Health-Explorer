-- create_login_roles.sql: one-off, per environment (dev and prod separately).
--
-- Creates a LOGIN role per consumer and makes it a member of the matching group
-- role from migration 002. Passwords come from the environment of the operator
-- running this, are never written to a file in the repo, and are never echoed.
-- Re-running rotates the passwords. Run as the database owner, over the direct
-- (non-pooled) connection:
--
--   export INGEST_DB_PASSWORD=... API_DB_PASSWORD=... ANALYST_DB_PASSWORD=...
--   psql "$DATABASE_URL_MIGRATE" -f db/ops/create_login_roles.sql
--
-- Then build DATABASE_URL_INGEST / _API / _ANALYST from these logins (pooled
-- host for API and analyst) and store them as platform secrets, not in git.
--
-- On Neon you may instead create the roles in the console or API; then only
-- `GRANT <group> TO <login>;` from the lines below is needed.

\set ON_ERROR_STOP on
\set ingest_pw `printenv INGEST_DB_PASSWORD`
\set api_pw `printenv API_DB_PASSWORD`
\set analyst_pw `printenv ANALYST_DB_PASSWORD`

-- An unset variable would create a login with no usable password. Stop instead.
SELECT (:'ingest_pw' = '' OR :'api_pw' = '' OR :'analyst_pw' = '') AS missing_pw \gset
\if :missing_pw
    \echo 'ERROR: set INGEST_DB_PASSWORD, API_DB_PASSWORD and ANALYST_DB_PASSWORD first'
    \quit
\endif

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'ingest_login', :'ingest_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ingest_login') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', 'ingest_login', :'ingest_pw') \gexec
GRANT ingest_writer TO ingest_login;

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'api_login', :'api_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api_login') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', 'api_login', :'api_pw') \gexec
GRANT api_reader TO api_login;

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'analyst_login', :'analyst_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analyst_login') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', 'analyst_login', :'analyst_pw') \gexec
GRANT analyst_readonly TO analyst_login;

-- Caveat: CREATE/ALTER ROLE sends the password to the server as text, so
-- server-side statement logging (log_statement = 'all') could record it. Use the
-- provider console for role creation if that logging is on.
