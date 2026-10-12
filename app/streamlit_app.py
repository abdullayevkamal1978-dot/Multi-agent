"""Interactive Streamlit front end for research-swarm."""
import asyncio
import os
import streamlit as st
from research_swarm import Settings, run_research
from research_swarm.report import render_html, render_json, render_markdown, render_pdf

st.set_page_config(page_title="Research Swarm", page_icon="🔎", layout="wide")
st.title("Research Swarm")
st.caption("Multi-agent research with cited findings and cross-source contradiction checks.")
with st.sidebar:
    st.header("Run settings")
    llm = st.selectbox("Language model", ["auto", "gemini", "openai", "anthropic", "mock"])
    search = st.selectbox("Search provider", ["auto", "exa", "tavily", "serpapi", "gemini", "mock"])
    exa_key = st.text_input("Exa API key", type="password", value=os.getenv("EXA_API_KEY", ""))
    llm_key = st.text_input("LLM API key (optional)", type="password")
    if llm != "auto" and llm != "mock":
        st.info("Enter an API key for the selected provider below. The mock model is always available.")
    questions = st.slider("Research branches", 2, 8, 4)
    result_count = st.slider("Results per query", 2, 10, 5)
topic = st.text_area("Research question", placeholder="e.g. What are the latest advances in grid-scale battery storage?")
if st.button("Run research", type="primary", disabled=not topic.strip()):
    key_field = {"gemini":"gemini_api_key", "openai":"openai_api_key", "anthropic":"anthropic_api_key"}.get(llm)
    overrides = {"llm_provider": llm, "search_provider": search,
                 "max_subquestions": questions, "results_per_query": result_count}
    if key_field and llm_key:
        overrides[key_field] = llm_key
    if exa_key:
        overrides["exa_api_key"] = exa_key
    settings = Settings.from_env().with_overrides(**overrides)
    with st.spinner("Planning, searching, reading sources, and synthesizing..."):
        try:
            report = asyncio.run(run_research(topic.strip(), settings))
            st.session_state["report"] = report
        except Exception as exc:
            st.error(f"Research run failed: {type(exc).__name__}: {exc}")
if report := st.session_state.get("report"):
    st.success(f"Completed with {len(report.sources)} sources · {report.stats.duration_seconds or 0:.1f}s")
    st.markdown(report.executive_summary or "No executive summary was produced.")
    col1, col2, col3 = st.columns(3)
    col1.metric("Sources", len(report.sources)); col2.metric("Findings", len(report.findings)); col3.metric("Contradictions", len(report.contradictions))
    with st.expander("Full report", expanded=True):
        st.markdown(render_markdown(report))
    d1, d2, d3 = st.columns(3)
    d1.download_button("Download Markdown", render_markdown(report), file_name="research-report.md", mime="text/markdown")
    d2.download_button("Download HTML", render_html(report), file_name="research-report.html", mime="text/html")
    try:
        pdf = render_pdf(report)
        d3.download_button("Download PDF", pdf, file_name="research-report.pdf", mime="application/pdf")
    except RuntimeError:
        d3.caption("Install the app extra to enable PDF export.")
    with st.expander("JSON data"):
        st.download_button("Download JSON", render_json(report), file_name="research-report.json", mime="application/json")
