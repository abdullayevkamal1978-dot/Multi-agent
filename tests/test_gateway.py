from app.gateway import _origin_matches_hosts


def test_same_origin_https_ignores_implicit_default_port():
    assert _origin_matches_hosts("https://example.com", ["example.com:443"])


def test_same_origin_accepts_forwarded_or_host_candidate():
    assert _origin_matches_hosts("https://example.com", ["internal.example:3000", "example.com"])


def test_same_origin_rejects_other_host_and_port():
    assert not _origin_matches_hosts("https://example.com", ["attacker.example", "example.com:444"])


def test_same_origin_rejects_http_https_port_mismatch():
    assert not _origin_matches_hosts("http://example.com", ["example.com:443"])
