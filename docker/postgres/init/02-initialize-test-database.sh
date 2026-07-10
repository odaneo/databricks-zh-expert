#!/usr/bin/env bash
set -Eeuo pipefail

test_database="${POSTGRES_TEST_DB:-databricks_agent_test}"
app_schema="${POSTGRES_SCHEMA:-databricks_agent}"

psql \
  --username "$POSTGRES_USER" \
  --dbname postgres \
  --set=ON_ERROR_STOP=1 \
  --set=test_database="$test_database" \
  --set=app_user="$POSTGRES_USER" <<'EOSQL'
SELECT format(
  'CREATE DATABASE %I OWNER %I',
  :'test_database',
  :'app_user'
)
WHERE NOT EXISTS (
  SELECT 1
  FROM pg_database
  WHERE datname = :'test_database'
) \gexec
EOSQL

psql \
  --username "$POSTGRES_USER" \
  --dbname "$test_database" \
  --set=ON_ERROR_STOP=1 \
  --set=app_schema="$app_schema" \
  --set=app_user="$POSTGRES_USER" \
  --set=test_database="$test_database" <<'EOSQL'
SELECT format(
  'CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I',
  :'app_schema',
  :'app_user'
) \gexec

SELECT format(
  'ALTER ROLE %I IN DATABASE %I SET search_path TO %I, pg_catalog',
  :'app_user',
  :'test_database',
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
