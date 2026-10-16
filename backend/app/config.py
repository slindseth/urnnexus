from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _default_appliance_root() -> Path:
    override = os.getenv("URN_NEXUS_APPLIANCE_ROOT") or os.getenv("APPLIANCE_ROOT")
    if override and override.strip():
        return Path(override).expanduser().resolve()

    # The appliance repository lives next to this repo in the current workspace.
    return Path(__file__).resolve().parents[3] / "appliance"


class ApplianceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    appliance_root: Path = Field(default_factory=_default_appliance_root)
    sample_projects_dirname: str = "sample_projects"
    runtime_dirname: str = ".riveanbud_runtime"
    onedrive_project_root_path: str = Field(
        default_factory=lambda: os.getenv(
            "URN_NEXUS_ONEDRIVE_PROJECT_ROOT", "AnbudAppliance/Urban_Reuse_Norway"
        )
    )
    memory_projects_file: Path | None = Field(
        default_factory=lambda: (
            Path(os.environ["URN_NEXUS_MEMORY_PROJECTS_FILE"]).expanduser()
            if os.getenv("URN_NEXUS_MEMORY_PROJECTS_FILE")
            else None
        )
    )
    memory_cli_root: Path | None = Field(
        default_factory=lambda: (
            Path(os.environ["URN_NEXUS_MEMORY_CLI_ROOT"]).expanduser()
            if os.getenv("URN_NEXUS_MEMORY_CLI_ROOT")
            else None
        )
    )
    memory_runtime_root: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "URN_NEXUS_MEMORY_RUNTIME_ROOT",
                str(Path(__file__).resolve().parents[2] / ".nexus-runtime"),
            )
        ).expanduser()
    )
    memory_actions_enabled: bool = Field(
        default_factory=lambda: (
            os.getenv("URN_NEXUS_MEMORY_ACTIONS_ENABLED", "true").lower() == "true"
        )
    )
    memory_provider: Literal["openai", "fixture"] = Field(
        default_factory=lambda: os.getenv("URN_NEXUS_MEMORY_PROVIDER", "openai")
    )

    def resolved_appliance_root(self) -> Path:
        return self.appliance_root.expanduser().resolve()

    def sample_projects_root(self) -> Path:
        return self.resolved_appliance_root() / self.sample_projects_dirname

    def runtime_roots(self) -> list[Path]:
        roots = [self.resolved_appliance_root() / self.runtime_dirname]
        runtime_override = os.getenv("RIVEANBUD_RUNTIME_DIR")
        if runtime_override and runtime_override.strip():
            roots.append(Path(runtime_override).expanduser())
        return list(dict.fromkeys(path.resolve(strict=False) for path in roots))

    def onedrive_project_root(self) -> str:
        return self.onedrive_project_root_path.strip().strip("/")
