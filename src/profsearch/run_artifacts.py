"""Deterministic run artifact helpers for pipeline and agent workflows."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from profsearch.config import Settings


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{os.getpid()}"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class RunArtifacts:
    def __init__(self, settings: Settings, command_name: str, run_id: str | None = None) -> None:
        self.settings = settings
        self.command_name = command_name
        self.run_id = run_id or make_run_id(command_name)
        self.path = settings.runs_path / self.run_id
        self.path.mkdir(parents=True, exist_ok=True)

    def file_path(self, name: str) -> Path:
        return self.path / name

    def write_json(self, name: str, payload: Any) -> Path:
        destination = self.file_path(name)
        destination.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
        return destination

    def write_text(self, name: str, content: str) -> Path:
        destination = self.file_path(name)
        destination.write_text(content, encoding="utf-8")
        return destination

    def append_jsonl(self, name: str, payload: Any) -> Path:
        destination = self.file_path(name)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_jsonable(payload), sort_keys=True))
            handle.write("\n")
        return destination


def load_run_summary(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


def latest_run_dir(settings: Settings) -> Path | None:
    candidates = [path for path in settings.runs_path.iterdir() if path.is_dir() and (path / "summary.json").exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


class PipelineRunReporter:
    def __init__(self, artifacts: RunArtifacts) -> None:
        self.artifacts = artifacts
        self.events_path = artifacts.file_path("events.jsonl")
        self.stage1_payload: dict[str, Any] = {"universities": [], "errors": []}
        self.stage2_payload: dict[str, Any] = {"sources": []}
        self.stage_summaries: dict[str, dict[str, Any]] = {}
        self.artifacts.write_json(
            "metadata.json",
            {
                "command": artifacts.command_name,
                "run_id": artifacts.run_id,
                "created_at": utcnow_iso(),
                "config_file": artifacts.settings.config_file_path,
                "profile": artifacts.settings.selected_profile,
            },
        )

    def emit(self, event_type: str, **payload: Any) -> None:
        self.artifacts.append_jsonl(
            "events.jsonl",
            {"at": utcnow_iso(), "event": event_type, **payload},
        )

    def stage_started(self, stage_name: str, **payload: Any) -> None:
        self.emit("stage_started", stage=stage_name, payload=payload)

    def stage_completed(self, stage_name: str, outcome: dict[str, Any]) -> None:
        self.stage_summaries[stage_name] = {"status": "completed", "outcome": outcome}
        self.emit("stage_completed", stage=stage_name, outcome=outcome)

    def stage_failed(self, stage_name: str, error: str, **payload: Any) -> None:
        self.stage_summaries[stage_name] = {"status": "failed", "error": error, **payload}
        self.emit("stage_failed", stage=stage_name, error=error, payload=payload)

    def record_stage1_university(self, payload: dict[str, Any]) -> None:
        self.stage1_payload["universities"].append(payload)

    def record_stage1_error(self, payload: dict[str, Any]) -> None:
        self.stage1_payload["errors"].append(payload)
        self.emit("stage1_error", payload=payload)

    def record_stage2_source(self, payload: dict[str, Any]) -> None:
        self.stage2_payload["sources"].append(payload)
        self.emit("stage2_source", payload=payload)

    def finalize(
        self,
        *,
        success: bool,
        results: list[tuple[str, dict[str, Any]]],
        failed_stage: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        if self.stage1_payload["universities"] or self.stage1_payload["errors"]:
            self.artifacts.write_json("stage1.json", self.stage1_payload)
        if self.stage2_payload["sources"]:
            self.artifacts.write_json("stage2.json", self.stage2_payload)
        summary = {
            "run_id": self.artifacts.run_id,
            "artifact_dir": self.artifacts.path,
            "success": success,
            "failed_stage": failed_stage,
            "error": error,
            "results": [{"stage": stage, "outcome": outcome} for stage, outcome in results],
            "stages": self.stage_summaries,
            "finished_at": utcnow_iso(),
        }
        self.artifacts.write_json("summary.json", summary)
        return _jsonable(summary)
