from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import sleep

import pytest

from backend.app.config import ApplianceSettings
from backend.app.services.appliance import ApplianceService


@pytest.mark.parametrize("snapshot", ["health", "activity_feed"])
def test_concurrent_status_requests_share_one_refresh_and_can_invalidate(tmp_path: Path, monkeypatch, snapshot: str) -> None:
    service = ApplianceService(ApplianceSettings(appliance_root=tmp_path))
    barrier = Barrier(8)
    builds = []

    def calculate():
        result = object()
        builds.append(result)
        sleep(0.05)
        return result

    monkeypatch.setattr(service, "_calculate_" + snapshot, calculate)
    cached = getattr(service, "_cached_" + snapshot)

    def request(_):
        barrier.wait(timeout=5)
        return cached()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(request, range(8)))

    assert len(builds) == 1
    assert all(result is builds[0] for result in results)
    invalidate = service._invalidate_health_cache if snapshot == "health" else service._invalidate_activity_cache
    invalidate()
    refreshed = cached()
    assert len(builds) == 2
    assert refreshed is builds[1]
