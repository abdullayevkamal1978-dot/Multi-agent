.PHONY: install test demo live clean

install:
	uv sync --extra app --extra all --extra dev

test:
	uv run pytest -q

demo:
	uv run research-swarm "solid-state battery commercialization timeline" --mock

live:
	uv run research-swarm "solid-state battery commercialization timeline" --out out/report.md --json out/report.json

clean:
	rm -rf out .cache .pytest_cache
