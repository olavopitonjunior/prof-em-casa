"""Testa o próprio hook de rastreabilidade (ac_traceability) com sessões internas do pytester."""

import ac_traceability
import pytest

CONFTEST = """
import ac_traceability

def pytest_configure(config):
    ac_traceability.register(config)
"""

OK_FILE = """
import pytest

@pytest.mark.ac("AC-01")
def test_one():
    pass

@pytest.mark.ac("AC-02")
def test_two():
    pass

def test_unmarked():
    pass
"""


@pytest.fixture
def inner(pytester, monkeypatch):
    monkeypatch.setattr(ac_traceability, "REQUIRED_ACS", frozenset({"AC-01", "AC-02"}))
    pytester.makeini("[pytest]\nmarkers =\n    ac(*ids): critério de aceite\n")
    pytester.makeconftest(CONFTEST)
    return pytester


def test_full_run_with_every_ac_passing_is_green(inner):
    inner.makepyfile(test_a=OK_FILE)
    r = inner.runpytest()
    r.assert_outcomes(passed=3)
    assert r.ret == pytest.ExitCode.OK


def test_missing_marker_fails_the_full_run_and_names_the_id(inner):
    inner.makepyfile(
        test_a=OK_FILE.replace('@pytest.mark.ac("AC-02")', "")  # AC-02 sem teste marcado
    )
    r = inner.runpytest()
    r.assert_outcomes(passed=3)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*AC sem teste marcado e aprovado*AC-02*"])
    assert not any("AC-01" in line and "sem teste" in line for line in r.outlines)


def test_a_failing_marked_test_does_not_count(inner):
    inner.makepyfile(
        test_a=OK_FILE.replace("def test_two():\n    pass", "def test_two():\n    assert 0")
    )
    r = inner.runpytest()
    r.assert_outcomes(passed=2, failed=1)
    r.stdout.fnmatch_lines(["*AC-02*"])
    assert r.ret == pytest.ExitCode.TESTS_FAILED


def test_a_skipped_marked_test_does_not_count(inner):
    inner.makepyfile(
        test_a=OK_FILE.replace(
            '@pytest.mark.ac("AC-02")', '@pytest.mark.ac("AC-02")\n@pytest.mark.skip'
        )
    )
    r = inner.runpytest()
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*AC sem teste marcado e aprovado*AC-02*"])


def test_one_marker_may_carry_several_ids(inner):
    inner.makepyfile(
        test_a="""
import pytest

@pytest.mark.ac("AC-01", "AC-02")
def test_both():
    pass
"""
    )
    assert inner.runpytest().ret == pytest.ExitCode.OK


def test_narrowed_runs_are_not_enforced(inner):
    inner.makepyfile(
        test_a=OK_FILE.replace('@pytest.mark.ac("AC-02")', ""), test_b="def test_b(): pass"
    )
    assert inner.runpytest("test_b.py").ret == pytest.ExitCode.OK  # arquivo
    assert inner.runpytest("-k", "unmarked").ret == pytest.ExitCode.OK  # -k
    assert inner.runpytest("test_a.py::test_one").ret == pytest.ExitCode.OK  # nodeid
    assert inner.runpytest("--deselect", "test_a.py::test_two").ret == pytest.ExitCode.OK
    assert inner.runpytest("-m", "not ac").ret == pytest.ExitCode.OK  # outro filtro de marcador


def test_marker_run_is_enforced(inner):
    inner.makepyfile(test_a=OK_FILE.replace('@pytest.mark.ac("AC-02")', ""))
    r = inner.runpytest("-m", "ac")
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*AC-02*"])
    inner.makepyfile(test_a=OK_FILE)
    assert inner.runpytest("-m", "ac").ret == pytest.ExitCode.OK


def test_explicit_testpaths_count_as_a_full_run(inner):
    inner.makeini("[pytest]\ntestpaths = .\nmarkers =\n    ac(*ids): critério de aceite\n")
    inner.makepyfile(test_a=OK_FILE.replace('@pytest.mark.ac("AC-02")', ""))
    assert inner.runpytest(".").ret == pytest.ExitCode.TESTS_FAILED


def test_the_real_required_set_is_the_ten_acs_of_increment_1():
    assert ac_traceability.INCREMENT_1_ACS == frozenset(
        {"AC-03", "AC-04", "AC-05", "AC-06", "AC-21", "AC-22", "AC-23", "AC-24", "AC-27", "AC-39"}
    )


def test_the_real_required_set_adds_the_seven_acs_of_increment_2():
    assert ac_traceability.INCREMENT_2_ACS == frozenset(
        {"AC-26", "AC-27", "AC-33", "AC-36", "AC-37", "AC-38", "AC-40"}
    )
    # AC-27 aparece nos dois incrementos (o 2 fecha o IDEMPOTENCY_CONFLICT): a união tem 16 ids.
    assert ac_traceability.REQUIRED_ACS == (
        ac_traceability.INCREMENT_1_ACS | ac_traceability.INCREMENT_2_ACS
    )
    assert len(ac_traceability.REQUIRED_ACS) == 16


def test_without_a_passing_ac38_test_the_full_run_fails_and_lists_it(inner, monkeypatch):
    monkeypatch.setattr(ac_traceability, "REQUIRED_ACS", ac_traceability.INCREMENT_2_ACS)
    tests = "\n".join(
        f'@pytest.mark.ac("{ac}")\ndef test_{ac.lower().replace("-", "_")}():\n    pass\n'
        for ac in sorted(ac_traceability.INCREMENT_2_ACS - {"AC-38"})
    )
    inner.makepyfile(test_a="import pytest\n\n" + tests)
    r = inner.runpytest()
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*AC sem teste marcado e aprovado*AC-38*"])
    assert not any("AC-26" in line and "sem teste" in line for line in r.outlines)
