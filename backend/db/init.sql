-- Runs exactly once, on first initialization of the pgdata volume.
-- If you already have a populated volume from a prior run, this will NOT
-- re-run — enable the extension manually in that case:
--   docker compose exec db psql -U vrp -d vrp -c "CREATE EXTENSION IF NOT EXISTS postgis;"

CREATE EXTENSION IF NOT EXISTS postgis;

-- topology is optional but useful if you ever need to model road segments
-- as a graph inside Postgres itself, rather than only via OSRM.
CREATE EXTENSION IF NOT EXISTS postgis_topology;
