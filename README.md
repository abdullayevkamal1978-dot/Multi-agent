# Research Swarm

**A multi-agent deep-research system built with LangGraph.** Give it a question: it plans research branches, searches the web in parallel, reads pages, checks sources for disagreements, and produces a cited report.

## Highlights

- Parallel research branches with isolated errors and URL-based citation deduplication.
- Structured Pydantic outputs for planning, claims, contradictions, and synthesis.
- Exa, Tavily, SerpAPI, Gemini Grounding, and deterministic offline mock search providers.
- Respect for each origin's `robots.txt`; disallowed pages are not fetched, and unavailable robots policies fail closed (HTTP 404 means no published policy).
- CLI and Python API, plus an optional Streamlit interface.
- Markdown, JSON, HTML, and PDF exports.
- Offline end-to-end tests that require no API keys.

## Quick start

```bash
uv sync --extra google --extra dev
cp .env.example .env  # add provider keys as needed

# Fully offline demo; no API keys or network access
uv run research-swarm "solid-state battery commercialization timeline" --mock

# Run the web UI
uv sync --extra app --extra google
uv run streamlit run app/streamlit_app.py
```

## Provider configuration

| Layer | Supported providers | Purpose |
|---|---|---|
| LLM | Gemini, OpenAI, Anthropic, mock | Planning, claim extraction, contradiction checks, synthesis |
| Search | Exa, Tavily, SerpAPI, Gemini Grounding, mock | Finding source pages |

Set `LLM_PROVIDER` and `SEARCH_PROVIDER` to a provider name, or leave them as `auto` to select an available configured provider. Keys are read from environment variables: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `EXA_API_KEY`, `TAVILY_API_KEY`, and `SERPAPI_API_KEY`.

### Exa live smoke test

The Exa provider uses Exa's `/search` endpoint with the `x-api-key` header. To verify your own Exa account and key with one real query:

```bash
export EXA_API_KEY="your-exa-api-key"
uv run research-swarm "recent advances in grid-scale battery storage" \
  --provider gemini --search exa --max-subquestions 2 --results-per-query 2 \
  --out out/exa-live-report.md --json out/exa-live-report.json
```

This command runs the full research pipeline and writes a report that records `search:exa` in its run metadata. Use a valid LLM key as well, or set `--provider mock` if you only want to verify Exa search results without a real synthesis model. **A live Exa request has not been performed from this repository session because no Exa API key was available here.** No live-test result is claimed.

> A mock search corpus is explicitly synthetic and must not be cited as factual evidence. Real research requires a live search provider and a configured LLM.

## Web UI

The Streamlit UI is a one-question research workspace with provider selection, optional API-key entry, configurable research breadth, report preview, and Markdown/JSON/HTML/PDF downloads. Keys entered in the UI are used only for the current app process; for production deployments use environment secrets rather than shared/public app inputs.

```bash
uv sync --extra app --extra google
uv run streamlit run app/streamlit_app.py
```

For local development without a paid LLM, select the `mock` model and `mock` search provider.

## CLI

```bash
# Offline, deterministic run
uv run research-swarm "quantum error correction progress" --mock

# Save Markdown and JSON
uv run research-swarm "tidal energy economics" --out out/report.md --json out/report.json

# Choose providers and tune parallelism
uv run research-swarm "grid-scale storage" --provider gemini --search exa \
  --max-subquestions 6 --results-per-query 5 --concurrency 8

# Print only the report
uv run research-swarm "topic" --quiet
```

Progress logs go to stderr; the report goes to stdout unless an output file is specified.

## Python API

```python
import asyncio
from research_swarm import Settings, run_research

async def main():
    settings = Settings(llm_provider="gemini", search_provider="exa", max_subquestions=5)
    report = await run_research("tidal energy economics", settings)
    print(report.executive_summary)
    for finding in report.findings:
        print(finding.heading, finding.source_ids, finding.confidence)

asyncio.run(main())
```

## Architecture

```text
START → PLANNER → parallel RESEARCHER branches → CROSS-CHECK → SYNTHESIZER → REPORT
                       search → read → extract claims
```

The planner creates independent questions. LangGraph `Send()` fans them out to isolated researcher nodes. Each branch searches, deduplicates URLs, checks `robots.txt`, reads allowed pages, and extracts source-backed claims. The cross-check agent identifies disagreements, then synthesis creates findings, an executive summary, and open questions. Errors are retained as run warnings instead of silently discarding the rest of the run.

## Exports

The Python API exposes `render_markdown`, `render_json`, `render_html`, and `render_pdf`. HTML is self-contained and print-friendly. PDF generation is available with the `app` extra (`reportlab`). The Streamlit UI offers downloads for each format.

## Tests

```bash
uv run pytest -q
```

The test suite is designed to run offline and without provider keys. It covers configuration, provider resolution, page extraction and cache, citations, mock end-to-end graph execution, concurrency, and report rendering. Live provider tests are intentionally opt-in and require user-supplied credentials.

## Project layout

```text
src/research_swarm/
  agents/                 planner, researcher, cross-check, synthesis
  providers/              Exa, Tavily, SerpAPI, Gemini, mock, page fetcher
  models.py               Pydantic report schemas
  graph.py                LangGraph topology and fan-out
  runner.py               end-to-end Python entry point
  report.py               Markdown, JSON, HTML, and PDF rendering
  cli.py                  command-line interface
app/streamlit_app.py       interactive web interface
 tests/                    offline pytest suite
```

## Limitations

- Research quality depends on the selected search provider, source quality, and LLM. Citations are constrained to collected sources, but citations do not prove that a claim is true.
- `robots.txt` is checked per origin and cached for the process. If its policy cannot be retrieved, crawling is blocked conservatively; sites returning 404 are treated as having no published robots policy.
- Live Exa/Tavily/SerpAPI verification requires API credentials and is not represented as completed in this repository session.
- The mock provider is for demos and tests only; its generated pages are fictional.
