from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Mapping, Sequence

from repo_harness_lab.domain.trace_models import CommandExecutionRecord


@dataclass(frozen=True, slots=True)
class CommandExecutionError(RuntimeError):
    record: CommandExecutionRecord

    def __str__(self) -> str:
        command = " ".join(self.record.command)
        return f"command failed with exit code {self.record.exit_code}: {command}"


class CommandExecutor:
    def run(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: int | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = False,
    ) -> CommandExecutionRecord:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf8",
            errors="replace",
            timeout=timeout_seconds,
            env=dict(env) if env is not None else None,
            check=False,
        )
        record = CommandExecutionRecord(
            command=tuple(command),
            cwd=str(cwd),
            exit_code=completed.returncode,
            stdout_excerpt=completed.stdout,
            stderr_excerpt=completed.stderr,
        )
        if check and record.exit_code != 0:
            raise CommandExecutionError(record)
        return record
