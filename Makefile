.PHONY: install install-dev test run demo compose schemas

install:
	python3 scripts/bootstrap.py

install-dev:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest -q

run:
	FIXTURES=1 python3 -m uvicorn eve_miro.api.main:app --reload --port 8000

demo:
	FIXTURES=1 python3 -m eve_miro.api.demo

compose:
	docker compose config

schemas:
	python3 -c "from pathlib import Path; from eve_miro.schemas.export import export_schemas; export_schemas(Path('schemas'))"
