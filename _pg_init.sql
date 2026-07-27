-- Check available extensions
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name LIKE '%vector%';

-- Create database and user
CREATE USER raguser WITH PASSWORD 'ragpass';
CREATE DATABASE ragdb OWNER raguser;
GRANT ALL PRIVILEGES ON DATABASE ragdb TO raguser;

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector CASCADE;
