"""
Tests for src/cache_cleaner.py and the `heatmap clear` subcommand.
"""

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

from src.cache_cleaner import CacheTarget, clear_caches, find_cache_targets, path_size


def _build_checkout(root: Path) -> None:
    """Create a checkout-shaped tree with caches, build output and protected dirs."""
    (root / "pkg" / "__pycache__").mkdir(parents=True)
    (root / "pkg" / "__pycache__" / "a.pyc").write_bytes(b"x" * 100)
    (root / ".ruff_cache").mkdir()
    (root / ".pytest_cache").mkdir()
    (root / ".mypy_cache").mkdir()
    (root / "htmlcov").mkdir()
    (root / "build").mkdir()
    (root / "dist").mkdir()
    (root / "pkg.egg-info").mkdir()
    (root / ".coverage").write_bytes(b"y" * 10)
    # Protected: must never be listed or walked into.
    (root / ".venv" / "__pycache__").mkdir(parents=True)
    (root / ".git" / "objects").mkdir(parents=True)
    # Application cache.
    (root / "cache").mkdir()
    (root / "cache" / "cache.pkl").write_bytes(b"z" * 50)


class TestFindCacheTargets:
    """Tests for find_cache_targets."""

    def test_finds_app_and_dev_caches(self, tmp_path):
        _build_checkout(tmp_path)

        targets = find_cache_targets(tmp_path, tmp_path / "cache")
        found = {t.path.resolve() for t in targets}

        assert (tmp_path / "cache").resolve() in found  # app cache
        assert (tmp_path / "pkg" / "__pycache__").resolve() in found
        assert (tmp_path / ".ruff_cache").resolve() in found
        assert (tmp_path / ".pytest_cache").resolve() in found
        assert (tmp_path / ".mypy_cache").resolve() in found
        assert (tmp_path / "htmlcov").resolve() in found
        assert (tmp_path / "build").resolve() in found
        assert (tmp_path / "dist").resolve() in found
        assert (tmp_path / "pkg.egg-info").resolve() in found
        assert (tmp_path / ".coverage").resolve() in found

    def test_never_touches_vcs_or_virtualenv(self, tmp_path):
        _build_checkout(tmp_path)

        found = {t.path.resolve() for t in find_cache_targets(tmp_path, tmp_path / "cache")}

        assert not any(".venv" in str(p) for p in found)
        assert not any(".git" in str(p) for p in found)

    def test_kinds_are_labelled(self, tmp_path):
        _build_checkout(tmp_path)

        kinds = {t.kind for t in find_cache_targets(tmp_path, tmp_path / "cache")}

        assert kinds == {"app cache", "dev cache", "build artifact"}

    def test_missing_app_cache_is_not_listed(self, tmp_path):
        _build_checkout(tmp_path)

        targets = find_cache_targets(tmp_path, tmp_path / "does_not_exist")

        assert all(t.kind != "app cache" for t in targets)

    def test_empty_tree_has_no_targets(self, tmp_path):
        assert find_cache_targets(tmp_path, tmp_path / "cache") == []


class TestClearCaches:
    """Tests for clear_caches and path_size."""

    def test_removes_every_target_and_reports_bytes(self, tmp_path):
        _build_checkout(tmp_path)
        targets = find_cache_targets(tmp_path, tmp_path / "cache")

        removed, freed = clear_caches(targets)

        assert removed == len(targets)
        assert freed > 0
        assert all(not t.path.exists() for t in targets)

    def test_dry_run_deletes_nothing(self, tmp_path):
        _build_checkout(tmp_path)
        targets = find_cache_targets(tmp_path, tmp_path / "cache")

        removed, freed = clear_caches(targets, dry_run=True)

        assert removed == 0
        assert freed > 0
        assert all(t.path.exists() for t in targets)

    def test_path_size_sums_directory_tree(self, tmp_path):
        (tmp_path / "d").mkdir()
        (tmp_path / "d" / "a").write_bytes(b"a" * 30)
        (tmp_path / "d" / "b").write_bytes(b"b" * 12)
        (tmp_path / "single").write_bytes(b"c" * 7)

        assert path_size(tmp_path / "d") == 42
        assert path_size(tmp_path / "single") == 7
        assert path_size(tmp_path / "missing") == 0


class TestClearCommand:
    """The `clear` subcommand wiring in main.py."""

    def test_subcommand_parses_with_dry_run(self, monkeypatch):
        import main

        monkeypatch.setattr(sys, "argv", ["heatmap", "clear", "--dry-run"])
        args = main.parse_args()

        assert args.command == "clear"
        assert args.dry_run is True

    def test_run_clear_reports_and_calls_the_cleaner(self, monkeypatch, capsys):
        import main

        calls: dict = {}
        monkeypatch.setattr(main, "Config", lambda *a, **k: SimpleNamespace(cache_dir=Path("/x")))
        monkeypatch.setattr(
            main,
            "find_cache_targets",
            lambda root, app_cache_dir=None: [CacheTarget(Path("/tmp/devcache"), "dev cache")],
        )

        def fake_clear(targets, dry_run=False):
            calls["dry_run"] = dry_run
            return (len(list(targets)), 2048)

        monkeypatch.setattr(main, "clear_caches", fake_clear)

        main.run_clear(argparse.Namespace(dev=False, config=None, dry_run=False))

        out = capsys.readouterr().out
        assert "Removed 1 cache(s)" in out
        assert "2 KB" in out
        assert calls["dry_run"] is False

    def test_run_clear_dry_run_reports_without_deleting(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr(main, "Config", lambda *a, **k: SimpleNamespace(cache_dir=Path("/x")))
        monkeypatch.setattr(
            main,
            "find_cache_targets",
            lambda root, app_cache_dir=None: [CacheTarget(Path("/tmp/devcache"), "dev cache")],
        )
        monkeypatch.setattr(main, "clear_caches", lambda targets, dry_run=False: (0, 4096))

        main.run_clear(argparse.Namespace(dev=False, config=None, dry_run=True))

        out = capsys.readouterr().out
        assert "Would remove 1 cache(s)" in out
