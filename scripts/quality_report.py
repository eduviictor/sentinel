import argparse
import json
import logging
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

MARKER = "<!-- quality-report -->"
DEFAULT_DIR = "quality-fragments"
SUMMARY_LIMIT = 300
COMMAND_NOT_FOUND = 127
FAILED_RESULTS = frozenset({"failure", "cancelled"})

ORDER = [
    "ruff-check",
    "ruff-format",
    "mypy",
    "import-linter",
    "pytest",
    "bandit",
    "pip-audit",
    "vulture",
    "xenon",
    "mutation",
]

LABELS = {
    "ruff-check": "Lint (ruff)",
    "ruff-format": "Format (ruff)",
    "mypy": "Types (mypy)",
    "import-linter": "Architecture (import-linter)",
    "pytest": "Tests (pytest)",
    "bandit": "Security (bandit)",
    "pip-audit": "Dependencies (pip-audit)",
    "vulture": "Dead code (vulture)",
    "xenon": "Complexity (xenon)",
    "mutation": "Mutation (mutmut)",
}


class Fragment(TypedDict):
    name: str
    job: str
    exit_code: int
    duration: float
    summary: str


def last_line(output: str, exit_code: int) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if lines:
        return lines[-1][:SUMMARY_LIMIT]
    return "No issues found" if exit_code == 0 else f"Failed with exit code {exit_code}"


def execute(command: Sequence[str]) -> tuple[int, str]:
    try:
        process = subprocess.Popen(  # noqa: S603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        message = f"command not found: {command[0]}"
        sys.stdout.write(message + "\n")
        return COMMAND_NOT_FOUND, message
    if process.stdout is None:
        raise RuntimeError("subprocess stdout was not captured")
    captured: list[str] = []
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        captured.append(line)
    return process.wait(), "".join(captured)


def run(name: str, directory: Path, command: Sequence[str]) -> int:
    if not command:
        raise ValueError("no command given after '--'")
    started = time.monotonic()
    exit_code, output = execute(command)
    fragment = Fragment(
        name=name,
        job=os.environ.get("GITHUB_JOB", ""),
        exit_code=exit_code,
        duration=round(time.monotonic() - started, 2),
        summary=last_line(output, exit_code),
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps(fragment), encoding="utf-8")
    logger.info("%s finished with exit code %d", name, exit_code)
    return exit_code


def load_fragments(directory: Path) -> list[Fragment]:
    if not directory.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))
    ]


def sort_key(name: str) -> tuple[int, int, str]:
    if name in ORDER:
        return (0, ORDER.index(name), name)
    return (1, 0, name)


Row = tuple[str, bool, str]


def collect_rows(directory: Path, needs: dict[str, dict[str, str]]) -> list[Row]:
    fragments = load_fragments(directory)
    rows: list[Row] = [
        (fragment["name"], fragment["exit_code"] == 0, fragment["summary"])
        for fragment in fragments
    ]
    reported_jobs = {fragment.get("job", "") for fragment in fragments}
    rows.extend(
        (job, False, "job failed before reporting")
        for job, info in needs.items()
        if info.get("result") in FAILED_RESULTS and job not in reported_jobs
    )
    return sorted(rows, key=lambda row: sort_key(row[0]))


def format_row(row: Row) -> str:
    name, passed, summary = row
    cell = summary.replace("|", "\\|")
    return f"| {LABELS.get(name, name)} | {'✅' if passed else '❌'} | {cell} |"


def render(directory: Path, needs: dict[str, dict[str, str]]) -> str:
    rows = collect_rows(directory, needs)
    failing = sum(1 for _, passed, _ in rows if not passed)
    header = "✅ All good" if failing == 0 else f"❌ {failing} failing"
    lines = [MARKER, "", header, "", "| Check | Status | Result |", "| --- | --- | --- |"]
    lines.extend(format_row(row) for row in rows)
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quality_report")
    sub = parser.add_subparsers(dest="action", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("name")
    run_parser.add_argument("--dir", default=DEFAULT_DIR)
    render_parser = sub.add_parser("render")
    render_parser.add_argument("--dir", default=DEFAULT_DIR)
    render_parser.add_argument("--output", required=True)
    render_parser.add_argument("--needs-json", default="{}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if "--" in arguments:
        split = arguments.index("--")
        command = arguments[split + 1 :]
        arguments = arguments[:split]
    args = build_parser().parse_args(arguments)
    if args.action == "run":
        return run(args.name, Path(args.dir), command)
    needs = json.loads(args.needs_json)
    Path(args.output).write_text(render(Path(args.dir), needs), encoding="utf-8")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
