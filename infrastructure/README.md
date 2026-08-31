# Infrastructure

Local-only. No Kubernetes.

## Compose

```bash
docker compose up --build                 # postgres/postgis, redis, minio, api
docker compose --profile streaming up     # + Redpanda (optional)
docker compose --profile timeseries up    # + note sidecar; series stay on PostGIS
```

Default `docker compose up` must keep working without profiles.

Postgres image is `postgis/postgis:16-3.4`. Timescale is **future** and must not
replace this image (hypertables vs geography).

## MinIO prefixes

Bucket `eve-miro` (see `MINIO_BUCKET`):

| prefix | contents |
|---|---|
| `raw/` | untouched provider payloads |
| `normalized/` | WorldEvent JSON |
| `derived/` | WorldState snapshots |
| `simulation/` | traces, SIMULATED output |
| `experiments/` | scenario artifacts |

Kinds stay labeled: raw/normalized are typically OBSERVED or FORECAST;
`derived/` is DERIVED; `simulation/` is SIMULATED. Never mix.
