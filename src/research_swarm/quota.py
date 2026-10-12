"""In-memory budget guard for the optional site-owned Exa credential."""
from __future__ import annotations

import threading
import time

WINDOW_SECONDS = 24 * 60 * 60
MAX_SHARED_EXA_RUNS_PER_PROCESS_PER_DAY = 20
_lock = threading.Lock()
_attempts: list[float] = []


def reserve_shared_exa_slot(now: float | None = None) -> tuple[bool, int]:
    """Reserve one attempt; return ``(allowed, slots_left)`` for this process.

    This is a best-effort guard, not an account-wide billing limit: container
    restarts and multiple replicas have independent in-memory windows.
    """
    current = time.time() if now is None else now
    cutoff = current - WINDOW_SECONDS
    with _lock:
        _attempts[:] = [attempt for attempt in _attempts if attempt > cutoff]
        if len(_attempts) >= MAX_SHARED_EXA_RUNS_PER_PROCESS_PER_DAY:
            return False, 0
        _attempts.append(current)
        return True, MAX_SHARED_EXA_RUNS_PER_PROCESS_PER_DAY - len(_attempts)
