from research_swarm import quota


def test_shared_exa_budget_stops_at_process_limit(monkeypatch):
    monkeypatch.setattr(quota, "_attempts", [])
    for index in range(quota.MAX_SHARED_EXA_RUNS_PER_PROCESS_PER_DAY):
        allowed, _ = quota.reserve_shared_exa_slot(now=10_000 + index)
        assert allowed is True
    assert quota.reserve_shared_exa_slot(now=11_000) == (False, 0)


def test_shared_exa_budget_releases_expired_attempts(monkeypatch):
    monkeypatch.setattr(quota, "_attempts", [100.0])
    allowed, remaining = quota.reserve_shared_exa_slot(now=100 + quota.WINDOW_SECONDS + 1)
    assert allowed is True
    assert remaining == quota.MAX_SHARED_EXA_RUNS_PER_PROCESS_PER_DAY - 1
