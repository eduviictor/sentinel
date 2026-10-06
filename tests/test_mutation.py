import subprocess
from pathlib import Path
from types import ModuleType
from typing import ClassVar

import mutation
import pytest

DIFF = """\
diff --git a/src/pkg/a.py b/src/pkg/a.py
--- a/src/pkg/a.py
+++ b/src/pkg/a.py
@@ -3 +3 @@ def f():
-    return 1
+    return 2
@@ -10,0 +11,3 @@ def g():
+    a = 1
+    b = 2
+    c = 3
@@ -20,2 +23,0 @@ def h():
-    x = 1
-    y = 2
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-a
+b
diff --git a/src/pkg/gone.py b/src/pkg/gone.py
--- a/src/pkg/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x
-y
"""

SOURCE = """\
def top() -> int:
    return 1


async def later() -> int:
    return 2


class Box:
    def first(self) -> int:
        return 1

    def second(self) -> int:
        value = 2
        return value
"""


def counts(killed: int, survived: int, ignored: int = 0) -> mutation.Counts:
    return mutation.Counts(
        total=killed + survived + ignored, killed=killed, survived=survived, ignored=ignored
    )


@pytest.fixture
def sut() -> ModuleType:
    return mutation


class TestParseDiffRanges:
    def test_should_return_added_line_ranges_per_file(self, sut: ModuleType) -> None:
        ranges = sut.parse_diff_ranges(DIFF)

        assert ranges["src/pkg/a.py"] == [(3, 3), (11, 13), (23, 24)]

    def test_should_treat_pure_deletion_as_the_surrounding_lines(self, sut: ModuleType) -> None:
        assert sut.parse_diff_ranges(DIFF)["src/pkg/a.py"][-1] == (23, 24)

    def test_should_skip_deleted_files(self, sut: ModuleType) -> None:
        assert "src/pkg/gone.py" not in sut.parse_diff_ranges(DIFF)


class TestIsMutableSource:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("src/pkg/a.py", True),
            ("src/pkg/a.md", False),
            ("tests/test_a.py", False),
            ("scripts/mutation.py", False),
        ],
    )
    def test_should_accept_only_python_under_src(
        self, sut: ModuleType, path: str, expected: bool
    ) -> None:
        assert sut.is_mutable_source(path) is expected


class TestModuleName:
    def test_should_drop_src_and_suffix(self, sut: ModuleType) -> None:
        assert sut.module_name("src/pkg/sub/a.py") == "pkg.sub.a"

    def test_should_name_a_package_init_after_the_package(self, sut: ModuleType) -> None:
        assert sut.module_name("src/pkg/sub/__init__.py") == "pkg.sub"


class TestChangedFunctions:
    def test_should_name_the_top_level_function_whose_body_changed(self, sut: ModuleType) -> None:
        assert sut.changed_functions(SOURCE, [(2, 2)]) == ["x_top"]

    def test_should_name_async_functions(self, sut: ModuleType) -> None:
        assert sut.changed_functions(SOURCE, [(6, 6)]) == ["x_later"]

    def test_should_name_methods_with_the_class(self, sut: ModuleType) -> None:
        assert sut.changed_functions(SOURCE, [(15, 15)]) == ["xǁBoxǁsecond"]

    def test_should_ignore_changes_outside_function_bodies(self, sut: ModuleType) -> None:
        assert sut.changed_functions(SOURCE, [(1, 1), (3, 4), (9, 9)]) == []

    def test_should_return_every_function_a_range_touches(self, sut: ModuleType) -> None:
        assert sut.changed_functions(SOURCE, [(2, 11)]) == ["x_top", "x_later", "xǁBoxǁfirst"]


DECORATED = """\
@property
def prop():
    return 1


class Box:
    @staticmethod
    def plain():
        return 2

    @validator("x")
    def check(cls):
        return 3
"""


class TestDecoratedFunctions:
    def test_should_skip_decorated_functions_mutmut_ignores(self, sut: ModuleType) -> None:
        assert sut.changed_functions(DECORATED, [(1, 15)]) == ["xǁBoxǁplain"]


class TestMutantPatterns:
    def test_should_match_only_the_exact_function(self, sut: ModuleType) -> None:
        assert sut.mutant_patterns("pkg.a", ["x_top"]) == ["pkg.a.x_top__mutmut_*"]


class TestParseResults:
    def test_should_read_name_and_status_ignoring_noise(self, sut: ModuleType) -> None:
        output = (
            "UserWarning: something\n"
            "    pkg.a.x_top__mutmut_1: killed\n"
            "    pkg.a.x_top__mutmut_2: not checked\n"
            "    pkg.a.xǁBoxǁfirst__mutmut_1: survived\n"
        )

        assert sut.parse_results(output) == {
            "pkg.a.x_top__mutmut_1": "killed",
            "pkg.a.x_top__mutmut_2": "not checked",
            "pkg.a.xǁBoxǁfirst__mutmut_1": "survived",
        }


class TestCountStatuses:
    def test_should_exclude_not_checked_and_skipped_from_the_checked_mutants(
        self, sut: ModuleType
    ) -> None:
        results = {
            "a__mutmut_1": "killed",
            "a__mutmut_2": "survived",
            "a__mutmut_3": "not checked",
            "a__mutmut_4": "skipped",
            "a__mutmut_5": "timeout",
            "a__mutmut_6": "no tests",
        }

        assert sut.count_statuses(results) == {
            "total": 6,
            "killed": 2,
            "survived": 2,
            "ignored": 2,
        }


class TestScore:
    def test_should_divide_killed_by_checked(self, sut: ModuleType) -> None:
        assert sut.score(counts(killed=3, survived=1, ignored=5)) == 75.0

    def test_should_be_perfect_when_nothing_was_checked(self, sut: ModuleType) -> None:
        assert sut.score(counts(killed=0, survived=0, ignored=2)) == 100.0


class TestSummaryLine:
    def test_should_state_score_ratchet_killed_and_survivors(self, sut: ModuleType) -> None:
        line = sut.summary_line(counts(killed=44, survived=0), 95.0, 2)

        assert line == (
            "score 100.0% (ratchet 95%) · 44 of 44 mutants killed · 0 survivors in 2 changed files"
        )


class TestPassesRatchet:
    def test_should_pass_at_exactly_the_minimum(self, sut: ModuleType) -> None:
        assert sut.passes_ratchet(counts(killed=19, survived=1), 95.0) is True

    def test_should_fail_below_the_minimum(self, sut: ModuleType) -> None:
        assert sut.passes_ratchet(counts(killed=18, survived=2), 95.0) is False


class TestResolveMinScore:
    def test_should_prefer_the_cli_value(self, sut: ModuleType) -> None:
        assert sut.resolve_min_score(80.0, {"MUTATION_MIN_SCORE": "70"}) == 80.0

    def test_should_fall_back_to_the_environment(self, sut: ModuleType) -> None:
        assert sut.resolve_min_score(None, {"MUTATION_MIN_SCORE": "70"}) == 70.0

    def test_should_default_to_95(self, sut: ModuleType) -> None:
        assert sut.resolve_min_score(None, {}) == 95.0

    def test_should_fail_loudly_on_a_non_numeric_environment_value(self, sut: ModuleType) -> None:
        with pytest.raises(sut.MutationError):
            sut.resolve_min_score(None, {"MUTATION_MIN_SCORE": "high"})


class TestRunCommand:
    def test_should_return_stdout(self, sut: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, **_: subprocess.CompletedProcess(args, 0, "out", ""),
        )

        assert sut.run_command(["git", "status"]) == "out"

    def test_should_raise_with_stderr_when_the_command_fails(
        self, sut: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, **_: subprocess.CompletedProcess(args, 128, "", "bad ref"),
        )

        with pytest.raises(sut.MutationError, match="bad ref"):
            sut.run_command(["git", "merge-base", "nope", "HEAD"])


class TestGitDiff:
    def test_should_diff_against_the_merge_base(
        self, sut: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []

        def fake(args: list[str]) -> str:
            calls.append(args)
            return "abc123\n" if args[1] == "merge-base" else "the diff"

        monkeypatch.setattr(sut, "run_command", fake)

        assert sut.git_diff("origin/main") == "the diff"
        assert calls[0] == ["git", "merge-base", "origin/main", "HEAD"]
        assert calls[1][:5] == ["git", "diff", "-U0", "--no-color", "abc123"]


class TestChanged:
    @pytest.fixture
    def source_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        package = tmp_path / "src" / "pkg"
        package.mkdir(parents=True)
        (package / "a.py").write_text("def f() -> int:\n    return 2\n")
        monkeypatch.chdir(tmp_path)

    DIFF_OF_A = "+++ b/src/pkg/a.py\n@@ -2 +2 @@\n"

    def stub(
        self,
        sut: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        diff: str,
        results: dict[str, str],
    ) -> list[list[str]]:
        runs: list[list[str]] = []
        monkeypatch.setattr(sut, "git_diff", lambda base: diff)
        monkeypatch.setattr(sut, "run_mutmut", lambda patterns: runs.append(list(patterns)))
        monkeypatch.setattr(sut, "mutmut_results", lambda: results)
        return runs

    def test_should_report_nothing_to_mutate_without_running_mutmut(
        self,
        sut: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        runs = self.stub(sut, monkeypatch, "", {})

        assert sut.changed("main", 95.0) == 0
        assert capsys.readouterr().out == "No changed source code to mutate\n"
        assert runs == []

    @pytest.mark.usefixtures("source_tree")
    def test_should_run_mutmut_only_on_the_changed_function(
        self, sut: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runs = self.stub(sut, monkeypatch, self.DIFF_OF_A, {"pkg.a.x_f__mutmut_1": "killed"})

        sut.changed("main", 95.0)

        assert runs == [["pkg.a.x_f__mutmut_*"]]

    @pytest.mark.usefixtures("source_tree")
    def test_should_exit_zero_and_end_with_the_summary_when_above_the_ratchet(
        self,
        sut: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        results = {"pkg.a.x_f__mutmut_1": "killed", "pkg.other.x_g__mutmut_1": "survived"}
        self.stub(sut, monkeypatch, self.DIFF_OF_A, results)

        assert sut.changed("main", 95.0) == 0
        assert capsys.readouterr().out.splitlines()[-1] == (
            "score 100.0% (ratchet 95%) · 1 of 1 mutants killed · 0 survivors in 1 changed files"
        )

    @pytest.mark.usefixtures("source_tree")
    def test_should_exit_one_when_below_the_ratchet(
        self, sut: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        results = {"pkg.a.x_f__mutmut_1": "killed", "pkg.a.x_f__mutmut_2": "survived"}
        self.stub(sut, monkeypatch, self.DIFF_OF_A, results)

        assert sut.changed("main", 95.0) == 1

    @pytest.mark.usefixtures("source_tree")
    def test_should_pass_when_changed_functions_produce_no_mutants(
        self,
        sut: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self.stub(sut, monkeypatch, self.DIFF_OF_A, {})

        assert sut.changed("main", 95.0) == 0
        assert capsys.readouterr().out.strip().endswith(sut.NO_MUTANTS_MESSAGE)


class TestReport:
    RESULTS: ClassVar[dict[str, str]] = {
        "pkg.a.x_f__mutmut_1": "killed",
        "pkg.a.x_f__mutmut_2": "survived",
        "pkg.b.x_g__mutmut_1": "killed",
        "pkg.b.x_g__mutmut_2": "not checked",
    }

    def test_should_render_overall_score_module_table_and_survivors(self, sut: ModuleType) -> None:
        text = sut.render_report(self.RESULTS, 0.0)

        assert "Overall score: **66.7%**" in text
        assert "| pkg.a | 2 | 1 | 1 | 50.0% |" in text
        assert "| pkg.b | 1 | 1 | 0 | 100.0% |" in text
        assert text.split("### Surviving mutants")[1].strip() == "- `pkg.a.x_f__mutmut_2`"

    def test_should_exit_zero_by_default_even_with_survivors(
        self,
        sut: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sut, "mutmut_results", lambda: self.RESULTS)

        assert sut.report(0.0) == 0
        assert "### Surviving mutants" in capsys.readouterr().out

    def test_should_exit_one_below_the_min_score(
        self, sut: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sut, "mutmut_results", lambda: self.RESULTS)

        assert sut.report(90.0) == 1

    def test_should_fail_loudly_without_results(
        self, sut: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sut, "mutmut_results", lambda: {})

        with pytest.raises(sut.MutationError):
            sut.report(0.0)


class TestMain:
    def test_should_return_two_and_not_raise_on_a_mutation_error(
        self, sut: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sut, "mutmut_results", lambda: {})

        assert sut.main(["report"]) == 2
