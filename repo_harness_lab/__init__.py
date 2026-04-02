"""Repo-root bootstrap package for src-layout CLI usage."""

from __future__ import annotations

import pkgutil
from pathlib import Path

__all__ = ["__version__"]

__version__ = "0.1.0"

__path__ = pkgutil.extend_path(__path__, __name__)

_SRC_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "src" / "repo_harness_lab"
if _SRC_PACKAGE_DIR.is_dir():
    src_path = str(_SRC_PACKAGE_DIR)
    if src_path not in __path__:
        __path__.append(src_path)
