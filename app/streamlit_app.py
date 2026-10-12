"""Interactive, self-hosted research desk for research-swarm."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import streamlit as st

from research_swarm import Settings, run_research
from research_swarm.quota import reserve_shared_exa_slot
from research_swarm.report import render_html, render_json, render_markdown, render_pdf

st.set_page_config(page_title="Research Swarm", page_icon="⌁", layout="wide")
st.markdown(
    """
    <style>
    :root { --ink:#162b3d; --teal:#0d7f78; --paper:#f7f8f5; --line:#dce5e1; }
    .stApp { background:var(--paper); }
    [data-testid="stAppViewContainer"] .main .block-container { max-width:1240px; padding-top:1.4rem; }
    [data-testid="stSidebar"] { background:#edf2ef; border-right:1px solid var(--line); }
    [data-testid="stSidebar"] h2 { color:var(--ink); font-family:Georgia,serif; }
    .swarm-hero { min-height:210px; padding:2rem 2.2rem; border-radius:18px; color:#fff;
      background:linear-gradient(90deg,rgba(12,35,47,.94) 0%,rgba(13,55,62,.82) 48%,rgba(13,55,62,.14) 100%),url('/app/static/research-notebook.webp') center 52%/cover;
      display:flex; flex-direction:column; justify-content:center; box-shadow:0 12px 32px #193c351a; }
    .swarm-hero .eyebrow { color:#a9e1d5; letter-spacing:.16em; text-transform:uppercase; font-size:.72rem; font-weight:700; }
    .swarm-hero h1 { color:#fff; font:500 clamp(2.1rem,5vw,3.3rem)/1.05 Georgia,serif; margin:.5rem 0; }
    .swarm-hero p { max-width:620px; color:#e2eeea; font-size:1.02rem; margin:.25rem 0 0; }
    .section-label { color:var(--teal); font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; font-weight:750; }
    div.stButton > button[kind="primary"] { background:#087c74; border-color:#087c74; border-radius:10px; padding:.55rem 1.2rem; }
    div.stButton > button[kind="primary"]:hover { background:#06685f; border-color:#06685f; }
    [data-testid="stMetric"] { background:white; border:1px solid var(--line); border-radius:12px; padding:.8rem 1rem; }
    [data-testid="stDownloadButton"] button { border-radius:9px; }
    @media (max-width: 700px) { .swarm-hero { min-height:185px; padding:1.35rem; background-position:58% center; } }
    @media (prefers-reduced-motion: reduce) { *,*::before,*::after { scroll-behavior:auto!important; animation:none!important; transition:none!important; } }
    </style>
    <section class="swarm-hero">
      <span class="eyebrow">Evidence-first · multi-agent research</span>
      <h1>Research Swarm</h1>
      <p>Start with a question. Leave with cited findings, visible disagreements, and a report you can take with you.</p>
    </section>
    """,
    unsafe_allow_html=True,
)

NODE_LABELS = {
    "planner": "Building the research plan",
    "researcher": "Searching and reading source pages",
    "contradiction": "Cross-checking claims across sources",
    "synthesizer": "Writing the cited report",
    "finalize": "Finalizing report and citations",
}
LLM_KEY_FIELDS = {
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
}
SEARCH_KEY_FIELDS = {
    "exa": ("exa_api_key", "Exa API key"),
    "tavily": ("tavily_api_key", "Tavily API key"),
    "serpapi": ("serpapi_api_key", "SerpAPI key"),
    "gemini": ("gemini_api_key", "Gemini API key for Google Search grounding"),
}

with st.sidebar:
    st.markdown("## Run settings")
    llm = st.selectbox("Language model", ["auto", "gemini", "openai", "anthropic", "mock"], help="Auto uses the offline mock. Select a named provider and enter your own key to use a live LLM.")
    search = st.selectbox("Search provider", ["auto", "exa", "tavily", "serpapi", "gemini", "mock"])
    search_secret = ""
    search_field, search_label = SEARCH_KEY_FIELDS.get(search, ("", ""))
    site_exa_available = bool(os.getenv("EXA_API_KEY"))
    if search == "auto":
        search_field, search_label = "exa_api_key", "Optional personal Exa key (auto mode)"
    if search_field:
        search_secret = st.text_input(search_label, type="password", help="Your own key is used only in this active app session.")
    llm_secret = ""
    if llm in LLM_KEY_FIELDS:
        llm_secret = st.text_input(f"{llm.title()} LLM API key", type="password", help="Used for this session and never written to a file or database.")
    shared_exa = False
    if search == "exa" or (search == "auto" and site_exa_available):
        shared_exa = st.checkbox("Use the site's shared Exa credits for this run", value=False)
        if shared_exa:
            st.warning("Shared quota: at most 2 research branches, 2 results per query, 3 runs per browser session and 20 attempts per app process in each rolling 24-hour window. Limits are in-memory safeguards, not an account-wide billing cap; replicas/restarts have separate windows. Provider charges may apply after free credits are exhausted.")
    st.caption("Provider accounts may apply their own usage charges. Password fields are not stored in files or a database.")
    if llm == "mock" or search == "mock":
        st.info("Mock providers are for offline demos only; their generated evidence is synthetic.")
    branches = st.slider("Research branches", min_value=2, max_value=8, value=4)
    results_per_query = st.slider("Results per query", min_value=2, max_value=10, value=5)

st.markdown('<div class="section-label">Your research brief</div>', unsafe_allow_html=True)
topic = st.text_area("Research question", placeholder="What are the latest advances in grid-scale battery storage?", height=100, label_visibility="collapsed")
run_clicked = st.button("Run research", type="primary", disabled=not topic.strip())

if run_clicked:
    now = datetime.now(timezone.utc).timestamp()
    recent_runs = [value for value in st.session_state.get("shared_exa_runs", []) if now - value < 86400]
    using_shared_exa = shared_exa and site_exa_available and not search_secret
    if shared_exa and not site_exa_available and not search_secret:
        st.error("The shared Exa key is not configured. Enter your own Exa key or choose another search provider.")
    elif using_shared_exa and len(recent_runs) >= 3:
        st.error("This browser session has used its three shared Exa runs for the last 24 hours. Use your own Exa key or try again later.")
    elif using_shared_exa and not reserve_shared_exa_slot(now)[0]:
        st.error("The shared Exa allowance for this application process is used up for the last 24 hours. Use your own Exa key or try again later.")
    else:
        if using_shared_exa:
            st.session_state["shared_exa_runs"] = recent_runs + [now]
        overrides: dict[str, object] = {
            "llm_provider": "mock" if llm == "auto" else llm,
            "search_provider": ("exa" if using_shared_exa or (search == "auto" and search_secret) else "mock") if search == "auto" else search,
            "max_subquestions": min(branches, 2) if using_shared_exa else branches,
            "results_per_query": min(results_per_query, 2) if using_shared_exa else results_per_query,
            "max_concurrency": 2 if using_shared_exa else 5,
        }
        if search_field:
            # Never silently fall back to a server-owned credential: shared quota requires an explicit opt-in.
            overrides[search_field] = search_secret if search_secret else (None if using_shared_exa else "")
        if llm in LLM_KEY_FIELDS:
            llm_field = LLM_KEY_FIELDS[llm]
            overrides[llm_field] = llm_secret or (search_secret if llm == "gemini" and search == "gemini" else "")
        settings = Settings.from_env().with_overrides(**overrides)
        progress = st.status("Starting research swarm…", expanded=True)
        try:
            def on_event(node_name: str, _update: dict) -> None:
                progress.write(f"• {NODE_LABELS.get(node_name, node_name.replace('_', ' ').capitalize())}")

            report = asyncio.run(run_research(topic.strip(), settings, on_event=on_event))
            st.session_state["report"] = report
            progress.update(label="Research complete", state="complete", expanded=False)
        except Exception as exc:
            progress.update(label="Research run stopped", state="error", expanded=True)
            st.error(f"The run could not be completed: {type(exc).__name__}: {exc}")
            st.info("Check the selected provider and API key, then run the same question again. Previous reports remain available below.")

report = st.session_state.get("report")
if report:
    st.divider()
    st.markdown(f"### {report.topic}")
    st.caption(f"{report.stats.llm_provider or 'unknown'} · {report.stats.search_provider or 'unknown'} search · {report.stats.duration_seconds or 0:.1f}s")
    m1, m2, m3 = st.columns(3)
    m1.metric("Sources", len(report.sources))
    m2.metric("Findings", len(report.findings))
    m3.metric("Disagreements", len(report.contradictions))
    tab_report, tab_sources, tab_run = st.tabs(["Research report", "Sources", "Run details"])
    with tab_report:
        st.markdown("#### Executive summary")
        st.markdown(report.executive_summary or "No executive summary was produced.")
        st.markdown(render_markdown(report))
    with tab_sources:
        if report.sources:
            for source in report.sources:
                status = "Read" if source.fetched else "Not read"
                st.markdown(f"**[{source.id}] [{source.title or source.url}]({source.url})** · {status}")
                if source.error:
                    st.caption(f"Source note: {source.error}")
        else:
            st.info("No sources were retrieved in this run.")
    with tab_run:
        st.json(report.stats.model_dump(mode="json"))
        if report.stats.errors:
            st.warning("Some branches reported errors; the rest of the report may still be useful.")
            for error in report.stats.errors:
                st.code(error)
    st.markdown("#### Export report")
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("Markdown", render_markdown(report), file_name="research-report.md", mime="text/markdown", use_container_width=True)
    d2.download_button("JSON", render_json(report), file_name="research-report.json", mime="application/json", use_container_width=True)
    d3.download_button("HTML", render_html(report), file_name="research-report.html", mime="text/html", use_container_width=True)
    try:
        d4.download_button("PDF", render_pdf(report), file_name="research-report.pdf", mime="application/pdf", use_container_width=True)
    except RuntimeError as exc:
        d4.caption(str(exc))

st.markdown("<small>Research Swarm · source quality matters; citations support traceability, not truth.</small>", unsafe_allow_html=True)
