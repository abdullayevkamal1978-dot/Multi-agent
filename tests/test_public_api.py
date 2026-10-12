"""The documented public API must import and work."""

import research_swarm
from research_swarm import Settings, render_markdown, run_research


def test_package_exports_the_documented_surface():
    for name in ("Settings", "run_research", "render_markdown", "render_json", "__version__"):
        assert hasattr(research_swarm, name), f"missing export: {name}"


def test_exported_objects_are_the_real_ones():
    from research_swarm.config import Settings as RealSettings
    from research_swarm.runner import run_research as real_run

    assert Settings is RealSettings
    assert run_research is real_run


async def test_end_to_end_through_the_public_api(settings):
    report = await run_research("public api smoke test", settings)
    assert render_markdown(report).startswith("# public api smoke test")
