# ruff: noqa: S603, S607
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ONLY = ["scripts/init.sh", "tests/test_init.py", "docs/superpowers", "uv.lock"]
NO_HOOKS = ("-c", "core.hooksPath=/dev/null")
# no GIT_* from the hook (it exports the template's index) and no host git config
CLEAN_ENV = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")} | {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def run(repo: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=repo, env=CLEAN_ENV, capture_output=True, text=True, check=False
    )


def template_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=TEMPLATE_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [path for path in listed.split("\0") if path and (TEMPLATE_ROOT / path).is_file()]


@pytest.fixture
def fresh_copy(tmp_path: Path) -> Path:
    repo = tmp_path / "copy"
    for relative in template_files():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATE_ROOT / relative, target)
    for command in (
        ("git", "init", "-q", "-b", "main"),
        ("git", "add", "-A"),
        ("git", *NO_HOOKS, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "t"),
    ):
        subprocess.run(command, cwd=repo, env=CLEAN_ENV, check=True, capture_output=True)
    return repo


def init(repo: Path, name: str) -> subprocess.CompletedProcess[str]:
    return run(repo, "sh", "scripts/init.sh", name)


def test_init_renames_the_package_and_removes_the_template_parts(fresh_copy: Path):
    result = init(fresh_copy, "net-monitor")

    assert result.returncode == 0, result.stderr
    assert (fresh_copy / "src/net_monitor/__init__.py").is_file()
    assert not (fresh_copy / "src/skeleton").exists()
    assert 'name = "net-monitor"' in (fresh_copy / "pyproject.toml").read_text()
    assert (fresh_copy / "README.md").read_text() == "# net-monitor\n"
    for leftover in TEMPLATE_ONLY:
        assert not (fresh_copy / leftover).exists(), leftover


def test_init_leaves_no_skeleton_in_any_file(fresh_copy: Path):
    assert init(fresh_copy, "net-monitor").returncode == 0

    mentions = [
        path.relative_to(fresh_copy)
        for path in fresh_copy.rglob("*")
        if path.is_file()
        and ".git" not in path.relative_to(fresh_copy).parts
        and b"skeleton" in path.read_bytes()
    ]
    assert mentions == []


def test_the_renamed_smoke_test_passes(fresh_copy: Path):
    assert init(fresh_copy, "net-monitor").returncode == 0

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_smoke.py"],
        cwd=fresh_copy,
        env={**CLEAN_ENV, "PYTHONPATH": str(fresh_copy / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout


def test_git_stays_healthy_after_init(fresh_copy: Path):
    assert init(fresh_copy, "net-monitor").returncode == 0

    assert run(fresh_copy, "git", "fsck").returncode == 0
    assert run(fresh_copy, "git", "status").returncode == 0


@pytest.mark.parametrize("name", ["Net Monitor", "net-", "a--b", "9lives", "json"])
def test_init_refuses_a_bad_name_without_touching_anything(fresh_copy: Path, name: str):
    result = init(fresh_copy, name)

    assert result.returncode != 0
    assert "invalid name" in result.stderr
    assert run(fresh_copy, "git", "status", "--porcelain").stdout == ""


def test_init_refuses_an_already_initialised_checkout(fresh_copy: Path):
    run(fresh_copy, "git", "mv", "src/skeleton", "src/other")
    run(
        fresh_copy,
        "git",
        *NO_HOOKS,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-qm",
        "t",
    )

    result = init(fresh_copy, "net-monitor")

    assert result.returncode != 0
    assert "already initialised" in result.stderr
    assert run(fresh_copy, "git", "status", "--porcelain").stdout == ""


def test_init_refuses_a_copy_without_git(fresh_copy: Path):
    shutil.rmtree(fresh_copy / ".git")
    before = {path: path.read_bytes() for path in fresh_copy.rglob("*") if path.is_file()}

    result = init(fresh_copy, "net-monitor")

    assert result.returncode != 0
    assert "not tracked by git" in result.stderr
    assert {path: path.read_bytes() for path in fresh_copy.rglob("*") if path.is_file()} == before
