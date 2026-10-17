-- Local development only. Creates separate non-superuser login roles for
-- migration/admin, import, API, and worker (spec 11.6). Passwords here are
-- local fixtures; deployed credentials come from Secrets Manager.
CREATE ROLE ops_admin  LOGIN PASSWORD 'ops_admin_local';
CREATE ROLE ops_import LOGIN PASSWORD 'ops_import_local';
CREATE ROLE ops_api    LOGIN PASSWORD 'ops_api_local';
CREATE ROLE ops_worker LOGIN PASSWORD 'ops_worker_local';
CREATE DATABASE ops OWNER ops_admin;
\connect ops
ALTER SCHEMA public OWNER TO ops_admin;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE ops FROM PUBLIC;
GRANT CONNECT ON DATABASE ops TO ops_import, ops_api, ops_worker;
