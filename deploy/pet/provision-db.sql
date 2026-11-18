\set ON_ERROR_STOP on

-- Run on the target cluster as a database administrator, connected to postgres.
DO $$
BEGIN
  IF current_database() <> 'postgres' THEN
    RAISE EXCEPTION 'Run pet provisioning while connected to postgres';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marong_pet_owner') THEN
    CREATE ROLE marong_pet_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marong_pet') THEN
    CREATE ROLE marong_pet LOGIN;
  END IF;
  IF EXISTS (
    SELECT FROM pg_roles
    WHERE rolname IN ('marong_pet_owner', 'marong_pet') AND
      (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls OR
       rolcanlogin <> (rolname = 'marong_pet'))
  ) OR EXISTS (
    SELECT FROM pg_auth_members m
    JOIN pg_roles r ON r.oid = m.member
    WHERE r.rolname IN ('marong_pet_owner', 'marong_pet')
  ) THEN
    RAISE EXCEPTION 'The existing pet roles do not match the required privileges';
  END IF;
  IF EXISTS (
    SELECT FROM pg_database
    WHERE datname = 'marong_pet' AND datdba <> 'marong_pet_owner'::regrole
  ) THEN
    RAISE EXCEPTION 'The existing pet database has an unexpected owner';
  END IF;
END
$$;

SELECT 'CREATE DATABASE marong_pet OWNER marong_pet_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'marong_pet')
\gexec

REVOKE ALL ON DATABASE marong_pet FROM PUBLIC;
GRANT CONNECT ON DATABASE marong_pet TO marong_pet;

\connect marong_pet
\ir ../../marong/pet/schema.sql
