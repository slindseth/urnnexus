from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.app.config import ApplianceSettings
from backend.app.services.appliance import ApplianceService


def _history_entry(project: str, version: str) -> dict[str, object]:
    return {
        "project_name": project,
        "timestamp": "2026-06-12T09:00:00+02:00",
        "local_report_path": f"/missing/{project} - Kommentardokument - {version}.docx",
        "documents": [{"unused_large_data": "x" * 1000}],
    }


def _service(tmp_path: Path) -> tuple[ApplianceService, Path]:
    history = tmp_path / "outputs" / "history.jsonl"
    history.parent.mkdir()
    history.write_text(
        "\n".join(json.dumps(_history_entry(name, "1.0")) for name in ("Alpha", "Beta")) + "\n",
        encoding="utf-8",
    )
    return ApplianceService(ApplianceSettings(appliance_root=tmp_path)), history


def test_shared_report_history_is_read_once_across_concurrent_project_requests(tmp_path: Path, monkeypatch) -> None:
    service, history = _service(tmp_path)
    original_open = Path.open
    reads: list[Path] = []

    def counted_open(path: Path, *args, **kwargs):
        if path == history:
            reads.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted_open)
    names = ["Alpha", "Beta"] * 4
    with ThreadPoolExecutor(max_workers=8) as pool:
        reports = list(pool.map(service._history_report_candidates, names))

    assert [rows[0].report_name for rows in reports] == [
        f"{name} - Kommentardokument - 1.0.docx" for name in names
    ]
    assert len(reads) == 1


def test_report_history_cache_refreshes_after_append_and_same_size_replacement(tmp_path: Path) -> None:
    service, history = _service(tmp_path)
    assert len(service._history_report_candidates("Alpha")) == 1
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_history_entry("Alpha", "2.0")) + "\n")
    assert len(service._history_report_candidates("Alpha")) == 2

    original_stat = history.stat()
    replacement = history.with_suffix(".new")
    replacement.write_text(history.read_text().replace("2.0", "3.0"), encoding="utf-8")
    os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    replacement.replace(history)
    reports = service._history_report_candidates("Alpha")
    assert {row.version for row in reports} == {"1.0", "3.0"}


def test_report_history_ignores_malformed_lines_and_non_object_json(tmp_path: Path) -> None:
    service, history = _service(tmp_path)
    with history.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n[]\nnull\n")
    assert len(service._history_report_candidates("Alpha")) == 1
