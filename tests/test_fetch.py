from research_swarm.providers.fetch import PageFetcher, extract_text
from research_swarm.providers.mock import MockSearchProvider, slugify

HTML = """
<html><head><title>Real Title</title>
<style>body{color:red}</style><script>var x=1;</script></head>
<body><nav>menu junk</nav><h1>Heading</h1><p>First paragraph.</p>
<div>Second block</div><p>Third.</p><footer>footer junk</footer></body></html>
"""


def test_extract_text_drops_script_style_and_boilerplate():
    title, text = extract_text(HTML)
    assert title == "Real Title"
    assert "var x=1" not in text
    assert "color:red" not in text
    assert "menu junk" not in text
    assert "footer junk" not in text
    assert "First paragraph." in text and "Third." in text


def test_extract_text_survives_malformed_markup():
    title, text = extract_text("<p>unclosed <b>bold <div>next")
    assert "unclosed" in text


async def test_mock_page_is_synthesized_offline(settings):
    fetcher = PageFetcher(settings)
    title, text, error = await fetcher.fetch("https://mock.example/some-topic/critique")
    assert error is None
    assert "Some Topic" in title and "Critique" in title
    assert len(text) > 100


async def test_page_cache_round_trip(tmp_path, settings):
    cache_pages = tmp_path / "cache" / "pages"
    fetcher = PageFetcher(settings)
    url = "https://mock.example/cached-topic/data"
    first = await fetcher.fetch(url)
    assert cache_pages.exists() and list(cache_pages.glob("*.json"))

    # A brand-new fetcher instance must serve from the disk cache.
    second = await PageFetcher(settings).fetch(url)
    assert first == second


def test_slugify_distinguishes_similar_queries():
    a = slugify("solid state batteries current state")
    b = slugify("solid state batteries research 2026")
    assert a != b


async def test_mock_search_returns_distinct_urls(settings):
    provider = MockSearchProvider(settings)
    hits = await provider.search("some topic", max_results=5)
    assert len(hits) == 5
    assert len({h.url for h in hits}) == 5
