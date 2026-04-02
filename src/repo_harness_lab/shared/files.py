from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import stat
from pathlib import Path


IGNORED_PARTS = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc"}
BINARY_SENTINEL = b"\x00"



def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path



def copy_directory(source: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination



def remove_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, onerror=_retry_remove_readonly)



def _retry_remove_readonly(func, target: str, exc_info) -> None:
    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    func(target)


def collect_changed_files(source: Path, target: Path) -> tuple[str, ...]:
    source_snapshot = _snapshot_directory(source)
    target_snapshot = _snapshot_directory(target)
    changed = []
    for relative_path in sorted(set(source_snapshot) | set(target_snapshot)):
        if source_snapshot.get(relative_path) != target_snapshot.get(relative_path):
            changed.append(relative_path)
    return tuple(changed)



def build_patch(source: Path, target: Path) -> str:
    fragments: list[str] = []
    for relative_path in collect_changed_files(source, target):
        fragment = _build_file_patch(
            relative_path,
            _read_bytes_if_exists(source / Path(relative_path)),
            _read_bytes_if_exists(target / Path(relative_path)),
        )
        if fragment:
            fragments.append(fragment)
    return "\n\n".join(fragments)



def _snapshot_directory(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not root.exists():
        return snapshot

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _should_ignore(relative):
            continue
        snapshot[relative.as_posix()] = _file_digest(path)
    return snapshot



def _build_file_patch(relative_path: str, source_bytes: bytes | None, target_bytes: bytes | None) -> str:
    left_label = f"a/{relative_path}"
    right_label = f"b/{relative_path}"

    if _is_binary(source_bytes) or _is_binary(target_bytes):
        return _binary_patch_notice(relative_path, source_bytes, target_bytes)

    source_lines = _decode_text(source_bytes).splitlines()
    target_lines = _decode_text(target_bytes).splitlines()
    diff_lines = list(
        difflib.unified_diff(
            source_lines,
            target_lines,
            fromfile=left_label,
            tofile=right_label,
            lineterm="",
        )
    )
    if not diff_lines:
        return ""
    return "\n".join([f"diff --git {left_label} {right_label}", *diff_lines])



def _binary_patch_notice(relative_path: str, source_bytes: bytes | None, target_bytes: bytes | None) -> str:
    left_label = f"a/{relative_path}"
    right_label = f"b/{relative_path}"
    if source_bytes is None:
        notice = f"Binary file added: {right_label}"
    elif target_bytes is None:
        notice = f"Binary file deleted: {left_label}"
    else:
        notice = f"Binary files differ: {left_label} {right_label}"
    return f"diff --git {left_label} {right_label}\n{notice}"



def _read_bytes_if_exists(path: Path) -> bytes | None:
    if not path.exists() or not path.is_file():
        return None
    return path.read_bytes()



def _should_ignore(relative: Path) -> bool:
    if any(part in IGNORED_PARTS for part in relative.parts):
        return True
    if relative.suffix in IGNORED_SUFFIXES:
        return True
    return False



def _file_digest(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()



def _is_binary(payload: bytes | None) -> bool:
    return payload is not None and BINARY_SENTINEL in payload



def _decode_text(payload: bytes | None) -> str:
    if payload is None:
        return ""
    return payload.decode("utf8", errors="replace")
