.PHONY: install test lint format run-api build-web run-dev docker-build docker-up docker-down clean doctor info export-web

install:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -q

test-cov:
	python -m pytest tests/ --cov=lexiforge --cov-report=term-missing

lint:
	ruff check lexiforge tests web scripts

format:
	ruff format lexiforge tests web scripts

# --- dashboard -------------------------------------------------------------
build-web:
	cd web/frontend && npm ci && npm run build

run-api:
	uvicorn web.api:app --reload --host 127.0.0.1 --port 8000

# Build once, then serve API + dashboard from one process.
run-dev: build-web
	uvicorn web.api:app --reload --host 127.0.0.1 --port 8000

export-web:
	python scripts/export_web_data.py --transcripts transcripts --refs refs --out web/data

# --- containers ------------------------------------------------------------
docker-build:
	docker build -t lexiforge:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

# --- misc ------------------------------------------------------------------
doctor:
	python -m lexiforge.cli doctor

info:
	python -m lexiforge.cli info

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__') if p.is_dir()]"
	rm -rf .pytest_cache .coverage htmlcov lexiforge.db
	rm -rf web/frontend/dist
