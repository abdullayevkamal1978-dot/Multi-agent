import urllib.robotparser

import pytest

from research_swarm.providers import fetch
from research_swarm.providers.fetch import PageFetcher


@pytest.mark.asyncio
async def test_robots_policy_blocks_disallowed_url(settings):
    origin = "https://robots-test.example"
    policy = urllib.robotparser.RobotFileParser()
    policy.parse(["User-agent: *", "Disallow: /private/"])
    fetch._ROBOTS_CACHE[origin] = policy
    reader = PageFetcher(settings)
    assert await reader._allowed_by_robots(origin + "/public/page") is True
    assert await reader._allowed_by_robots(origin + "/private/page") is False
    fetch._ROBOTS_CACHE.pop(origin, None)


@pytest.mark.asyncio
async def test_invalid_url_is_rejected_by_robots_check(settings):
    assert await PageFetcher(settings)._allowed_by_robots("file:///etc/passwd") is False
