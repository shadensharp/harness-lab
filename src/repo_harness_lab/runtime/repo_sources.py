from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from repo_harness_lab.config.settings import Settings, load_settings
from repo_harness_lab.domain.run_models import WorkspaceSession
from repo_harness_lab.domain.task_spec import RepoSource, RepoSourceKind, TaskSpec
from repo_harness_lab.runtime.executor import CommandExecutionError, CommandExecutor
from repo_harness_lab.shared.files import copy_directory, ensure_directory, remove_directory
from repo_harness_lab.shared.ids import new_id

_GIT_URL_PREFIXES = ("http://", "https://", "ssh://", "git://", "file://")
_SCP_LIKE_GIT_URL = re.compile(r"^[^@\\/\s]+@[^:\s]+:.+$")


@dataclass(frozen=True, slots=True)
class MaterializedRepoSource:
    repo_root: Path
    display_label: str
    cleanup_root: Path | None = None
    resolved_revision: str | None = None

    def cleanup(self) -> None:
        if self.cleanup_root is not None:
            remove_directory(self.cleanup_root)


def infer_repo_source_kind(value: str) -> RepoSourceKind:
    text = str(value).strip()
    if _looks_like_git_url(text):
        return RepoSourceKind.GIT_URL
    return RepoSourceKind.LOCAL_PATH


def display_repo_source_label(value: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    if infer_repo_source_kind(text) is RepoSourceKind.LOCAL_PATH:
        path = Path(text)
        return path.name or text

    parsed = urlparse(text)
    path = parsed.path.strip("/")
    if path:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2:
            tail = "/".join(parts[-2:])
        else:
            tail = parts[-1]
        return tail.removesuffix(".git") or text

    if _SCP_LIKE_GIT_URL.fullmatch(text):
        tail = text.split(":", 1)[1]
        return tail.removesuffix(".git") or text
    return text


def materialize_repo_source(
    repo_source: RepoSource,
    *,
    repo_revision: str | None = None,
    settings: Settings | None = None,
    executor: CommandExecutor | None = None,
    temp_label: str = "repo-source",
) -> MaterializedRepoSource:
    resolved_settings = settings or load_settings()
    resolved_executor = executor or CommandExecutor()
    resolved_settings.paths.ensure_runtime_directories()

    if repo_source.kind in {RepoSourceKind.LOCAL_PATH, RepoSourceKind.SNAPSHOT}:
        repo_root = Path(repo_source.path_or_url).resolve()
        if not repo_root.exists():
            raise FileNotFoundError(f"source repository does not exist: {repo_root}")
        is_git_repo = _is_git_repo(repo_root, resolved_executor)
        if repo_revision and not is_git_repo:
            raise ValueError("repo_revision requires a git repository source")
        if repo_revision:
            temp_root = ensure_directory(resolved_settings.paths.tmp_dir) / f"{_safe_file_stem(temp_label)}-{new_id('repo')}"
            pinned_root = temp_root / _repo_directory_name(str(repo_root))
            copy_directory(repo_root, pinned_root)
            _checkout_git_revision(pinned_root, repo_revision, resolved_executor)
            return MaterializedRepoSource(
                repo_root=pinned_root,
                display_label=display_repo_source_label(str(repo_root)),
                cleanup_root=temp_root,
                resolved_revision=_git_head_revision(pinned_root, resolved_executor),
            )
        return MaterializedRepoSource(
            repo_root=repo_root,
            display_label=display_repo_source_label(str(repo_root)),
            cleanup_root=None,
            resolved_revision=_git_head_revision(repo_root, resolved_executor) if is_git_repo else None,
        )

    if repo_source.kind is not RepoSourceKind.GIT_URL:
        raise NotImplementedError(f"unsupported repo source kind: {repo_source.kind.value}")

    temp_root = ensure_directory(resolved_settings.paths.tmp_dir) / f"{_safe_file_stem(temp_label)}-{new_id('repo')}"
    repo_root = temp_root / _repo_directory_name(repo_source.path_or_url)
    local_git_path = _local_git_url_path(repo_source.path_or_url)
    if local_git_path is not None:
        if not local_git_path.exists():
            raise FileNotFoundError(f"source repository does not exist: {local_git_path}")
        copy_directory(local_git_path, repo_root)
        if repo_revision:
            _checkout_git_revision(repo_root, repo_revision, resolved_executor)
        return MaterializedRepoSource(
            repo_root=repo_root,
            display_label=display_repo_source_label(repo_source.path_or_url),
            cleanup_root=temp_root,
            resolved_revision=_git_head_revision(repo_root, resolved_executor),
        )

    clone_command = ["git", "clone"]
    branch = str(repo_source.default_branch or "").strip()
    if not repo_revision:
        clone_command.extend(["--depth", "1"])
        if branch:
            clone_command.extend(["--branch", branch, "--single-branch"])
    clone_command.extend([_clone_source_argument(repo_source.path_or_url), str(repo_root)])

    try:
        resolved_executor.run(clone_command, cwd=resolved_settings.paths.tmp_dir, check=True)
    except CommandExecutionError as exc:
        remove_directory(temp_root)
        detail = exc.record.stderr_excerpt.strip() or exc.record.stdout_excerpt.strip() or str(exc)
        raise RuntimeError(f"git clone failed for {repo_source.path_or_url}: {detail}") from exc

    if repo_revision:
        try:
            _checkout_git_revision(repo_root, repo_revision, resolved_executor)
        except Exception:
            remove_directory(temp_root)
            raise

    return MaterializedRepoSource(
        repo_root=repo_root,
        display_label=display_repo_source_label(repo_source.path_or_url),
        cleanup_root=temp_root,
        resolved_revision=_git_head_revision(repo_root, resolved_executor),
    )


def resolve_workspace_source_repo_root(task: TaskSpec, workspace: WorkspaceSession) -> Path:
    metadata = workspace.metadata if isinstance(workspace.metadata, dict) else {}
    source_repo_root = str(metadata.get("source_repo_root") or task.repo_source.path_or_url).strip()
    return Path(source_repo_root).resolve()


def is_http_remote_git_url(value: str) -> bool:
    text = str(value).strip()
    if not text:
        return False
    if infer_repo_source_kind(text) is not RepoSourceKind.GIT_URL:
        return False
    parsed = urlparse(text)
    return parsed.scheme.lower() in {"http", "https"}


def _looks_like_git_url(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith(_GIT_URL_PREFIXES):
        return True
    return _SCP_LIKE_GIT_URL.fullmatch(value) is not None


def _local_git_url_path(value: str) -> Path | None:
    parsed = urlparse(value)
    if parsed.scheme.lower() != "file":
        return None
    local_path = url2pathname(unquote(parsed.path))
    if parsed.netloc:
        local_path = f"//{parsed.netloc}{local_path}"
    return Path(local_path)


def _clone_source_argument(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme.lower() != "file":
        return value
    local_path = url2pathname(unquote(parsed.path))
    if parsed.netloc:
        local_path = f"//{parsed.netloc}{local_path}"
    return str(Path(local_path))


def _repo_directory_name(value: str) -> str:
    label = display_repo_source_label(value).replace("/", "-")
    return _safe_file_stem(label) or "repo"


def _safe_file_stem(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in "._-" else "-" for char in value).strip("-")
    return sanitized or "repo-source"


def _is_git_repo(repo_root: Path, executor: CommandExecutor) -> bool:
    try:
        record = executor.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_root)
    except Exception:
        return False
    return record.exit_code == 0 and record.stdout_excerpt.strip().lower() == "true"


def _git_head_revision(repo_root: Path, executor: CommandExecutor) -> str | None:
    if not _is_git_repo(repo_root, executor):
        return None
    record = executor.run(["git", "rev-parse", "HEAD"], cwd=repo_root, check=True)
    return record.stdout_excerpt.strip() or None


def _checkout_git_revision(repo_root: Path, revision: str, executor: CommandExecutor) -> None:
    try:
        executor.run(["git", "checkout", "--detach", str(revision)], cwd=repo_root, check=True)
    except CommandExecutionError as exc:
        detail = exc.record.stderr_excerpt.strip() or exc.record.stdout_excerpt.strip() or str(exc)
        raise RuntimeError(f"git checkout failed for {revision}: {detail}") from exc
