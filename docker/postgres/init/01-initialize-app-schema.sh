#!/usr/bin/env bash
set -Eeuo pipefail

app_schema="${POSTGRES_SCHEMA:-databricks_agent}"

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=app_schema="$app_schema" \
  --set=app_user="$POSTGRES_USER" \
  --set=app_database="$POSTGRES_DB" <<'EOSQL'
SELECT format(
  'CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I',
  :'app_schema',
  :'app_user'
) \gexec

SELECT format(
  'ALTER ROLE %I IN DATABASE %I SET search_path TO %I, pg_catalog',
  :'app_user',
  :'app_database',
  :'app_schema'
) \gexec

SELECT format(
  'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA %I',
  :'app_schema'
) \gexec

SELECT format(
  'ALTER EXTENSION vector SET SCHEMA %I',
  :'app_schema'
)
WHERE EXISTS (
  SELECT 1
  FROM pg_extension AS extension
  JOIN pg_namespace AS namespace
    ON namespace.oid = extension.extnamespace
  WHERE extension.extname = 'vector'
    AND namespace.nspname <> :'app_schema'
) \gexec
EOSQL
