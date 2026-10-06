import argparse
import ast
import fnmatch
import logging
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

SOURCE_ROOT = "src"
DEFAULT_MIN_SCORE = 95.0
MIN_SCORE_ENV = "MUTATION_MIN_SCORE"
KILLED_STATUSES = frozenset({"killed", "timeout", "segfault", "caught by type check"})
IGNORED_STATUSES = frozenset({"skipped", "not checked"})
NO_CHANGES_MESSAGE = "No changed source code to mutate"
NO_MUTANTS_MESSAGE = "Changed functions produced no mutants"
NOTHING_MATCHES = "nothing matches"

Range = tuple[int, int]
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
RESULT_LINE = re.compile(r"^\s+(\S.*?): (.+)$")


class Counts(TypedDict):
    total: int
    killed: int
    survived: int
    ignored: int


class MutationError(Exception):
    pass


def parse_diff_ranges(diff: str) -> dict[str, list[Range]]:
    ranges: dict[str, list[Range]] = {}
    current: list[Range] | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            current = ranges.setdefault(target[2:], []) if target.startswith("b/") else None
            continue
        match = HUNK_HEADER.match(line)
        if match is None or current is None:
            continue
        start = int(match.group(1))
        length = 1 if match.group(2) is None else int(match.group(2))
        # A pure deletion leaves no added line; the surrounding lines mark where it happened.
        current.append((start, start + 1) if length == 0 else (start, start + length - 1))
    return {path: found for path, found in ranges.items() if found}


def is_mutable_source(path: str) -> bool:
    return path.endswith(".py") and path.startswith(f"{SOURCE_ROOT}/")


def module_name(path: str) -> str:
    parts = Path(path).relative_to(SOURCE_ROOT).with_suffix("").parts
    # mutmut names functions of a package's __init__.py after the package itself
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def is_mutated(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    # mutmut 3 skips decorated functions, except a lone @staticmethod or @classmethod
    match node.decorator_list:
        case []:
            return True
        case [ast.Name(id="staticmethod" | "classmethod")]:
            return True
        case _:
            return False


def overlaps(node: ast.FunctionDef | ast.AsyncFunctionDef, ranges: Sequence[Range]) -> bool:
    first = node.body[0].lineno
    last = node.end_lineno or first
    return any(start <= last and end >= first for start, end in ranges)


def changed_functions(source: str, ranges: Sequence[Range]) -> list[str]:
    names: list[str] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if is_mutated(node) and overlaps(node, ranges):
                names.append(f"x_{node.name}")
        elif isinstance(node, ast.ClassDef):
            names.extend(
                f"xǁ{node.name}ǁ{method.name}"
                for method in node.body
                if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef)
                and is_mutated(method)
                and overlaps(method, ranges)
            )
    return names


def mutant_patterns(module: str, functions: Sequence[str]) -> list[str]:
    return [f"{module}.{function}__mutmut_*" for function in functions]


def parse_results(output: str) -> dict[str, str]:
    results: dict[str, str] = {}
    for line in output.splitlines():
        match = RESULT_LINE.match(line)
        if match is not None and "__mutmut_" in match.group(1):
            results[match.group(1)] = match.group(2).strip()
    return results


def count_statuses(results: dict[str, str]) -> Counts:
    killed = sum(status in KILLED_STATUSES for status in results.values())
    ignored = sum(status in IGNORED_STATUSES for status in results.values())
    return Counts(
        total=len(results),
        killed=killed,
        survived=len(results) - killed - ignored,
        ignored=ignored,
    )


def score(counts: Counts) -> float:
    checked = counts["total"] - counts["ignored"]
    if checked == 0:
        return 100.0
    return counts["killed"] / checked * 100


def format_percent(value: float) -> str:
    return f"{value:.1f}%"


def summary_line(counts: Counts, min_score: float, files: int) -> str:
    checked = counts["total"] - counts["ignored"]
    return (
        f"score {format_percent(score(counts))} (ratchet {min_score:g}%) · "
        f"{counts['killed']} of {checked} mutants killed · "
        f"{counts['survived']} survivors in {files} changed files"
    )


def passes_ratchet(counts: Counts, min_score: float) -> bool:
    return score(counts) >= min_score


def resolve_min_score(cli_value: float | None, environ: dict[str, str]) -> float:
    if cli_value is not None:
        return cli_value
    raw = environ.get(MIN_SCORE_ENV)
    if raw is None:
        return DEFAULT_MIN_SCORE
    try:
        return float(raw)
    except ValueError as error:
        raise MutationError(f"{MIN_SCORE_ENV} must be a number, got {raw!r}") from error


def run_command(args: list[str]) -> str:
    logger.info("running %s", args)
    completed = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    if completed.returncode != 0:
        # mutmut reports its failures on stdout, so both streams are needed to diagnose a CI run
        output = "\n".join((completed.stdout + completed.stderr).strip().splitlines()[-30:])
        raise MutationError(f"{' '.join(args)} failed ({completed.returncode}):\n{output}")
    return completed.stdout


def git_diff(base: str) -> str:
    merge_base = run_command(["git", "merge-base", base, "HEAD"]).strip()
    return run_command(["git", "diff", "-U0", "--no-color", merge_base, "--", f"{SOURCE_ROOT}/"])


def run_mutmut(patterns: Sequence[str]) -> None:
    run_command([sys.executable, "-m", "mutmut", "run", *patterns])


def mutmut_results() -> dict[str, str]:
    return parse_results(run_command([sys.executable, "-m", "mutmut", "results", "--all", "true"]))


def collect_patterns(diff: str) -> tuple[list[str], int]:
    patterns: list[str] = []
    files = 0
    for path, ranges in parse_diff_ranges(diff).items():
        if not is_mutable_source(path):
            continue
        source_file = Path(path)
        if not source_file.exists():
            continue
        functions = changed_functions(source_file.read_text(encoding="utf-8"), ranges)
        if functions:
            files += 1
            patterns.extend(mutant_patterns(module_name(path), functions))
    return patterns, files


def select_results(results: dict[str, str], patterns: Sequence[str]) -> dict[str, str]:
    return {
        name: status
        for name, status in results.items()
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)
    }


def changed(base: str, min_score: float) -> int:
    patterns, files = collect_patterns(git_diff(base))
    if not patterns:
        sys.stdout.write(f"{NO_CHANGES_MESSAGE}\n")
        return 0
    try:
        run_mutmut(patterns)
    except MutationError as error:
        if NOTHING_MATCHES not in str(error):
            raise
        sys.stdout.write(f"{NO_MUTANTS_MESSAGE}\n")
        return 0
    selected = select_results(mutmut_results(), patterns)
    if not selected:
        sys.stdout.write(f"{NO_MUTANTS_MESSAGE}\n")
        return 0
    counts = count_statuses(selected)
    for name, status in selected.items():
        if status not in KILLED_STATUSES | IGNORED_STATUSES:
            sys.stdout.write(f"{status}: {name}\n")
    sys.stdout.write(f"{summary_line(counts, min_score, files)}\n")
    return 0 if passes_ratchet(counts, min_score) else 1


def module_of_mutant(name: str) -> str:
    return name.rsplit(".", 1)[0]


def render_report(results: dict[str, str], min_score: float) -> str:
    counts = count_statuses(results)
    checked = counts["total"] - counts["ignored"]
    per_module: dict[str, dict[str, str]] = {}
    for name, status in results.items():
        per_module.setdefault(module_of_mutant(name), {})[name] = status
    lines = [
        "## Mutation testing",
        "",
        f"Overall score: **{format_percent(score(counts))}** "
        f"({counts['killed']} of {checked} mutants killed, ratchet {min_score:g}%)",
        "",
        "| Module | Mutants | Killed | Survived | Score |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for module in sorted(per_module):
        module_counts = count_statuses(per_module[module])
        lines.append(
            f"| {module} | {module_counts['total'] - module_counts['ignored']} "
            f"| {module_counts['killed']} | {module_counts['survived']} "
            f"| {format_percent(score(module_counts))} |"
        )
    lines.extend(["", "### Surviving mutants", ""])
    survivors = sorted(
        name for name, status in results.items() if status not in KILLED_STATUSES | IGNORED_STATUSES
    )
    lines.extend(f"- `{name}`" for name in survivors or ["None"])
    return "\n".join(lines)


def report(min_score: float) -> int:
    results = mutmut_results()
    if not results:
        raise MutationError("mutmut has no results; run `mutmut run` first")
    sys.stdout.write(f"{render_report(results, min_score)}\n")
    return 0 if passes_ratchet(count_statuses(results), min_score) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mutation testing for changed code")
    commands = parser.add_subparsers(dest="command", required=True)
    changed_parser = commands.add_parser("changed")
    changed_parser.add_argument("--base", required=True)
    changed_parser.add_argument("--min-score", type=float, default=None)
    report_parser = commands.add_parser("report")
    report_parser.add_argument("--min-score", type=float, default=0.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    args = build_parser().parse_args(argv)
    try:
        if args.command == "changed":
            return changed(args.base, resolve_min_score(args.min_score, dict(os.environ)))
        return report(args.min_score)
    except MutationError as error:
        logger.error("%s", error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
