# MinIO object prefixes

Create bucket `eve-miro` (compose env `MINIO_BUCKET`). Keys:

```
raw/            # provider bytes, OBSERVED or FORECAST as labeled
normalized/     # WorldEvent JSON after quality
derived/        # WorldState snapshots (DERIVED)
simulation/     # engine traces — SIMULATED
experiments/    # scenario YAML copies and run manifests
```

Example:

```
mc alias set local http://localhost:9000 minioadmin minioadmin
mc mb -p local/eve-miro
printf '' | mc pipe local/eve-miro/raw/.keep
printf '' | mc pipe local/eve-miro/normalized/.keep
printf '' | mc pipe local/eve-miro/derived/.keep
printf '' | mc pipe local/eve-miro/simulation/.keep
printf '' | mc pipe local/eve-miro/experiments/.keep
```

Traces in v1 also land under `data/traces/` when MinIO is unused.
