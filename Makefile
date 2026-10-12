.PHONY: install test demo live web clean

install:
	uv sync --extra google --extra web --extra dev

test:
	uv run pytest -q

demo:
	uv run research-swarm "solid-state battery commercialization timeline" --mock

live:
	uv run research-swarm "solid-state battery commercialization timeline" --out out/report.md --json out/report.json

# Streaming web UI at http://127.0.0.1:8000 (RESEARCH_WEB_HOST/PORT override)
web:
	uv run research-web

web-demo:
	RESEARCH_WEB_PORT=8000 uv run research-web

clean:
	rm -rf out .cache .pytest_cache
