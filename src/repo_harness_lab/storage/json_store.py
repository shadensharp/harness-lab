from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import json
from typing import Any

from repo_harness_lab.config.settings import Settings, load_settings
from repo_harness_lab.domain.protocols import RunStore
from repo_harness_lab.domain.run_models import ArtifactRef, CostSummary, RunStatus, RunSummary
from repo_harness_lab.shared.files import ensure_directory


class JsonRunStore(RunStore):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        ensure_directory(self.settings.paths.runs_dir)

    def run_dir(self, run_id: str) -> Path:
        return self.settings.paths.runs_dir / run_id

    def summary_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "summary.json"

    def report_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "report.md"

    def html_report_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "report.html"

    def patch_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "patch.diff"

    def verifier_results_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "verifier_results.json"

    def events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def save_summary(self, summary: RunSummary) -> None:
        run_dir = ensure_directory(self.run_dir(summary.run_id))
        payload = _serialize_summary(summary)
        (run_dir / "summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf8",
        )

    def load_summary(self, run_id: str) -> RunSummary:
        path = self.summary_path(run_id)
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return deserialize_summary(payload)

    def list_runs(self, limit: int = 20) -> list[RunSummary]:
        summaries = []
        for path in sorted(
            self.settings.paths.runs_dir.glob("*/summary.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            summaries.append(deserialize_summary(payload))
            if len(summaries) >= limit:
                break
        return summaries



def _serialize_summary(summary: RunSummary) -> dict[str, Any]:
    payload = asdict(summary)
    payload["status"] = summary.status.value
    payload["started_at"] = summary.started_at.isoformat()
    payload["finished_at"] = summary.finished_at.isoformat() if summary.finished_at else None
    return payload



def deserialize_summary(payload: dict[str, Any]) -> RunSummary:
    artifacts = tuple(ArtifactRef(**item) for item in payload.get("artifact_index", ()))
    cost_payload = payload.get("cost_summary", {})
    return RunSummary(
        run_id=str(payload["run_id"]),
        task_id=str(payload["task_id"]),
        status=RunStatus(payload["status"]),
        started_at=datetime.fromisoformat(payload["started_at"]),
        finished_at=datetime.fromisoformat(payload["finished_at"]) if payload.get("finished_at") else None,
        duration_ms=payload.get("duration_ms"),
        cost_summary=CostSummary(**cost_payload),
        changed_files=tuple(payload.get("changed_files", ())),
        verifier_outcome=payload.get("verifier_outcome"),
        artifact_index=artifacts,
        notes=tuple(payload.get("notes", ())),
        metadata=dict(payload.get("metadata", {})),
    )
