"""Pydantic models for patches, the merge report and the run manifest."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["pending", "skipped", "done", "failed"]


class _Strict(BaseModel):
    """Reject unknown keys: a misspelt key (e.g. 'changes' for 'patches') must fail loudly,
    not validate as an empty patch file."""
    model_config = ConfigDict(extra="forbid")


class Patch(_Strict):
    row: int  # 1-based data row (header excluded)
    column: str
    old: str
    new: str
    reason: str
    ambiguous: bool = False


class Flag(_Strict):
    row: int
    note: str


class PatchError(_Strict):
    row: int | None = None
    column: str | None = None
    errorCategory: Literal["validation", "transient", "permission"]
    message: str


class PatchFile(_Strict):
    agent: Literal["agent1", "agent2"]
    run_timestamp: str
    patches: list[Patch]          # required: write [] when nothing changes
    flags: list[Flag] = Field(default_factory=list)
    errors: list[PatchError] = Field(default_factory=list)


class AppliedPatch(BaseModel):
    """An entry in merge_report.applied. Informational only (checks use the patch files), so
    unknown keys such as 'source' are ignored and 'reason' is optional."""
    row: int
    column: str
    old: str
    new: str
    reason: str = ""


class MergeReport(BaseModel):
    applied: list[AppliedPatch] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    ambiguous_dates: list[dict[str, Any]] = Field(default_factory=list)
    unverifiable: list[dict[str, Any]] = Field(default_factory=list)


class AgentState(BaseModel):
    status: Status = "pending"


class Manifest(BaseModel):
    run_timestamp: str
    source: str = "app1.csv"
    agents: dict[str, AgentState] = Field(default_factory=lambda: {
        "agent1": AgentState(), "agent2": AgentState(), "agent3": AgentState()})
    parallel_seconds: float | None = None


def new_manifest(run_timestamp: str) -> Manifest:
    return Manifest(run_timestamp=run_timestamp)


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate(json.loads(path.read_text()))


def save_manifest(path: Path, manifest: Manifest) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(manifest.model_dump_json(indent=2))
    os.replace(tmp, path)
