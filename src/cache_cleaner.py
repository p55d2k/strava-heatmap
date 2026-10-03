"""
Cache maintenance: find and remove the disposable data in a checkout.

Two kinds of cache accumulate:

* the application cache (parsed GPS tracks and activity start points) under the
  configured ``CACHE_DIR``, and
* developer-tool caches and build artifacts — ``__pycache__``, ``.ruff_cache``,
  ``.pytest_cache``, ``.mypy_cache``, ``.coverage``, ``build/``, ``dist/`` and
  ``*.egg-info``.

``heatmap clear`` removes both so a run can be reproduced from a clean tree
rather than silently reusing stale data.
"""

import contextlib
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Directory names that hold disposable caches wherever they appear in the tree.
DEV_CACHE_DIRS = (
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "htmlcov",
)
# Project-root directories that are build output rather than source.
BUILD_DIRS = ("build", "dist")
# Directories never worth walking into (VCS metadata, virtualenvs, dependencies).
PRUNE_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", ".agents"}
# Loose files that are disposable tool output.
DEV_CACHE_FILES = (".coverage",)


@dataclass(frozen=True)
class CacheTarget:
    """One path scheduled for removal, with a human-readable kind."""

    path: Path
    kind: str


def find_cache_targets(project_root, app_cache_dir=None) -> list[CacheTarget]:
    """Return every disposable cache / build path under ``project_root``.

    Args:
        project_root: Root of the checkout to scan.
        app_cache_dir: The application's cache directory (usually the configured
            ``CACHE_DIR``); included when it exists.

    Returns:
        Targets ordered as discovered, de-duplicated by resolved path. Existing
        files and directories only.
    """
    root = Path(project_root).resolve()
    targets: list[CacheTarget] = []
    seen: set[Path] = set()

    def add(path: Path, kind: str) -> None:
        if not path.exists():
            return
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        targets.append(CacheTarget(path, kind))

    if app_cache_dir is not None:
        add(Path(app_cache_dir), "app cache")

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        here = Path(dirpath)
        for name in list(dirnames):
            if name in DEV_CACHE_DIRS:
                add(here / name, "dev cache")
                dirnames.remove(name)  # no point walking into it
        if here == root:
            for name in BUILD_DIRS:
                if name in dirnames:
                    add(here / name, "build artifact")
                    dirnames.remove(name)
        for name in filenames:
            if name in DEV_CACHE_FILES:
                add(here / name, "dev cache")

    for egg_info in sorted(root.glob("*.egg-info")):
        add(egg_info, "build artifact")

    return targets


def path_size(path: Path) -> int:
    """Total bytes held by a file or directory tree (0 when unreadable)."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            with contextlib.suppress(OSError):
                total += (Path(dirpath) / name).stat().st_size
    return total


def clear_caches(targets: list[CacheTarget], dry_run: bool = False) -> tuple[int, int]:
    """Remove ``targets`` and return ``(removed_count, bytes_freed)``.

    With ``dry_run`` nothing is deleted, but the returned byte count is what
    would have been freed. A target that cannot be removed is logged and
    skipped so one locked file does not abort the whole clear.
    """
    removed = 0
    freed = 0
    for target in targets:
        size = path_size(target.path)
        if dry_run:
            freed += size
            continue
        try:
            if target.path.is_dir():
                shutil.rmtree(target.path)
            else:
                target.path.unlink()
        except OSError as e:
            log.warning(f"Could not remove {target.path}: {e}")
            continue
        removed += 1
        freed += size
    return removed, freed
