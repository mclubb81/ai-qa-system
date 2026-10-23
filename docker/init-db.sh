#!/bin/bash
# Runs once, only against a fresh (empty) data volume -- the official
# postgres image auto-creates POSTGRES_DB (qa_logs) but only that one
# database, so this creates the second one qa-agent needs.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE qa_config;
EOSQL
