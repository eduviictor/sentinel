import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import quality_report


@pytest.fixture
def sut() -> ModuleType:
    return quality_report


def write_fragment(
    directory: Path, name: str, exit_code: int, summary: str, job: str = "checks"
) -> None:
    fragment = {
        "name": name,
        "job": job,
        "exit_code": exit_code,
        "duration": 1.0,
        "summary": summary,
    }
    (directory / f"{name}.json").write_text(json.dumps(fragment))


def read_fragment(directory: Path, name: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((directory / f"{name}.json").read_text())
    return data


def python_command(source: str) -> list[str]:
    return [sys.executable, "-c", source]


class TestRun:
    def test_should_record_passing_command_and_return_zero(
        self, sut: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = sut.main(
            ["run", "ok", "--dir", str(tmp_path), "--", *python_command("print('a\\nb')")]
        )

        fragment = read_fragment(tmp_path, "ok")
        assert code == 0
        assert fragment["exit_code"] == 0
        assert fragment["summary"] == "b"
        assert isinstance(fragment["duration"], float)
        assert capsys.readouterr().out == "a\nb\n"

    def test_should_propagate_exit_code_of_failing_command(
        self, sut: ModuleType, tmp_path: Path
    ) -> None:
        code = sut.main(
            ["run", "bad", "--dir", str(tmp_path), "--", *python_command("raise SystemExit(3)")]
        )

        assert code == 3
        assert read_fragment(tmp_path, "bad")["exit_code"] == 3

    def test_should_report_missing_command_as_exit_127(
        self, sut: ModuleType, tmp_path: Path
    ) -> None:
        code = sut.main(["run", "ghost", "--dir", str(tmp_path), "--", "no-such-binary-xyz"])

        fragment = read_fragment(tmp_path, "ghost")
        assert code == 127
        assert fragment["exit_code"] == 127
        assert "command not found: no-such-binary-xyz" in str(fragment["summary"])

    def test_should_truncate_summary_to_300_chars(self, sut: ModuleType, tmp_path: Path) -> None:
        sut.main(["run", "long", "--dir", str(tmp_path), "--", *python_command("print('x' * 500)")])

        assert read_fragment(tmp_path, "long")["summary"] == "x" * 300

    def test_should_create_missing_fragment_directory(
        self, sut: ModuleType, tmp_path: Path
    ) -> None:
        target = tmp_path / "nested" / "fragments"

        sut.main(["run", "ok", "--dir", str(target), "--", *python_command("pass")])

        assert (target / "ok.json").is_file()


class TestRender:
    def render(self, sut: ModuleType, tmp_path: Path, needs: str = "{}") -> list[str]:
        output = tmp_path / "report.md"
        code = sut.main(
            ["render", "--dir", str(tmp_path), "--output", str(output), "--needs-json", needs]
        )
        assert code == 0
        return output.read_text().splitlines()

    def test_should_order_known_checks_first_then_unknown_alphabetically(
        self, sut: ModuleType, tmp_path: Path
    ) -> None:
        for name in ["zeta", "pytest", "alpha", "ruff-check", "mypy"]:
            write_fragment(tmp_path, name, 0, "fine")

        rows = self.render(sut, tmp_path)[6:]

        assert [row.split(" | ")[0] for row in rows] == [
            "| Lint (ruff)",
            "| Types (mypy)",
            "| Tests (pytest)",
            "| alpha",
            "| zeta",
        ]

    def test_should_show_all_good_header_when_nothing_fails(
        self, sut: ModuleType, tmp_path: Path
    ) -> None:
        write_fragment(tmp_path, "mypy", 0, "Success")

        lines = self.render(sut, tmp_path)

        assert lines[0] == "<!-- quality-report -->"
        assert "✅ All good" in lines
        assert "| Types (mypy) | ✅ | Success |" in lines

    def test_should_count_failures_in_header(self, sut: ModuleType, tmp_path: Path) -> None:
        write_fragment(tmp_path, "mypy", 1, "2 errors")
        write_fragment(tmp_path, "pytest", 1, "1 failed")
        write_fragment(tmp_path, "bandit", 0, "clean")

        lines = self.render(sut, tmp_path)

        assert "❌ 2 failing" in lines
        assert "| Types (mypy) | ❌ | 2 errors |" in lines

    def test_should_add_failed_row_for_job_without_fragment(
        self, sut: ModuleType, tmp_path: Path
    ) -> None:
        write_fragment(tmp_path, "mypy", 0, "Success")
        needs = json.dumps(
            {
                "mypy": {"result": "success"},
                "pytest": {"result": "failure"},
                "xenon": {"result": "skipped"},
            }
        )

        lines = self.render(sut, tmp_path, needs)

        assert "❌ 1 failing" in lines
        assert "| Tests (pytest) | ❌ | job failed before reporting |" in lines
        assert not any(line.startswith("| xenon") for line in lines)

    def test_should_not_duplicate_failed_job_that_left_a_fragment(
        self, sut: ModuleType, tmp_path: Path
    ) -> None:
        write_fragment(tmp_path, "ruff-check", 1, "Found 2 errors.", job="checks")
        write_fragment(tmp_path, "mypy", 0, "Success", job="checks")

        lines = self.render(sut, tmp_path, json.dumps({"checks": {"result": "failure"}}))

        assert "❌ 1 failing" in lines
        assert not any("job failed before reporting" in line for line in lines)

    def test_should_say_no_issues_when_a_passing_tool_prints_nothing(
        self, sut: ModuleType, tmp_path: Path
    ) -> None:
        sut.run("vulture", tmp_path, python_command("pass"))

        assert read_fragment(tmp_path, "vulture")["summary"] == "No issues found"

    def test_should_list_jobs_skipped_while_draft_without_failing(
        self, sut: ModuleType, tmp_path: Path
    ) -> None:
        write_fragment(tmp_path, "ruff-check", 0, "All checks passed!")

        lines = self.render(sut, tmp_path, json.dumps({"deep": {"result": "skipped"}}))

        assert "✅ All good" in lines
        assert "⏭ Skipped while the PR is a draft: deep" in lines
