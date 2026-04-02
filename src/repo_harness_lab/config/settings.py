from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys

from repo_harness_lab.shared.files import ensure_directory


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class AppPaths:
    project_root: Path
    runtime_root: Path
    runs_dir: Path
    reports_dir: Path
    tmp_dir: Path
    examples_dir: Path
    tests_dir: Path

    def ensure_runtime_directories(self) -> None:
        ensure_directory(self.runtime_root)
        ensure_directory(self.runs_dir)
        ensure_directory(self.reports_dir)
        ensure_directory(self.tmp_dir)


@dataclass(frozen=True, slots=True)
class Settings:
    paths: AppPaths
    python_executable: str
    keep_workspaces: bool = False


def load_settings(project_root: Path | None = None) -> Settings:
    root = Path(os.environ.get("REPO_HARNESS_LAB_PROJECT_ROOT", project_root or _default_project_root())).resolve()
    runtime_root = Path(os.environ.get("REPO_HARNESS_LAB_RUNTIME_ROOT", root / "runtime")).resolve()
    keep_workspaces = os.environ.get("REPO_HARNESS_LAB_KEEP_WORKSPACES", "0") == "1"

    paths = AppPaths(
        project_root=root,
        runtime_root=runtime_root,
        runs_dir=runtime_root / "runs",
        reports_dir=runtime_root / "reports",
        tmp_dir=runtime_root / "tmp",
        examples_dir=root / "examples",
        tests_dir=root / "tests",
    )
    return Settings(
        paths=paths,
        python_executable=sys.executable,
        keep_workspaces=keep_workspaces,
    )
