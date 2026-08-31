-- EVE-MIRO PostGIS init. Event store is append-only.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS worlds (
  id TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  region TEXT NOT NULL DEFAULT 'philippines',
  information_cutoff TIMESTAMPTZ,
  label TEXT
);

CREATE TABLE IF NOT EXISTS events (
  seq BIGSERIAL PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  world_id TEXT NOT NULL REFERENCES worlds(id),
  source JSONB NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  entity JSONB,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  provenance JSONB NOT NULL,
  temporal JSONB NOT NULL,
  information_cutoff TIMESTAMPTZ,
  provenance_kind TEXT NOT NULL CHECK (provenance_kind IN ('observed','derived','forecast','simulated'))
);

CREATE INDEX IF NOT EXISTS events_world_time ON events (world_id, observed_at);
CREATE INDEX IF NOT EXISTS events_kind ON events (provenance_kind);

-- Never mutate history.
CREATE OR REPLACE FUNCTION events_forbid_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'event store is append-only; updates/deletes are forbidden';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS events_no_update ON events;
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
FOR EACH ROW EXECUTE FUNCTION events_forbid_mutation();

DROP TRIGGER IF EXISTS events_no_delete ON events;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
FOR EACH ROW EXECUTE FUNCTION events_forbid_mutation();

CREATE TABLE IF NOT EXISTS snapshots (
  id TEXT PRIMARY KEY,
  world_id TEXT NOT NULL,
  timestamp TIMESTAMPTZ NOT NULL,
  information_cutoff TIMESTAMPTZ NOT NULL,
  state JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS simulations (
  id TEXT PRIMARY KEY,
  world_id TEXT NOT NULL,
  status TEXT NOT NULL,
  information_cutoff TIMESTAMPTZ NOT NULL,
  body JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS experiences (
  id TEXT PRIMARY KEY,
  simulation_id TEXT,
  layer TEXT NOT NULL,
  body JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
  id TEXT PRIMARY KEY,
  world_id TEXT NOT NULL,
  simulation_id TEXT,
  mae DOUBLE PRECISION,
  rmse DOUBLE PRECISION,
  body JSONB NOT NULL
);
