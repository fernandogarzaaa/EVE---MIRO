"""Tiny local demo helper. Prints the happy-path curl sequence."""

from __future__ import annotations


def main() -> None:
    print(
        """
# terminal 1
FIXTURES=1 python3 -m uvicorn eve_miro.api.main:app --port 8000

# terminal 2
curl -s -X POST localhost:8000/worlds -H 'content-type: application/json' \
  -d '{"id":"ph-demo","information_cutoff":"2026-08-31T10:00:00Z"}'
curl -s -X POST localhost:8000/worlds/ph-demo/ingest -H 'content-type: application/json' \
  -d '{"providers":["openmeteo","usgs"],"use_fixtures":true}'
curl -s localhost:8000/worlds/ph-demo/state
curl -s -X POST localhost:8000/simulations -H 'content-type: application/json' \
  -d '{"world_id":"ph-demo","scenario":"typhoon_manila_001","population":200}'
# then POST /simulations/{id}/run
open http://127.0.0.1:8000/
"""
    )


if __name__ == "__main__":
    main()
