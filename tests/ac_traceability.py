"""Rastreabilidade AC x teste (Spec Parte III §1; plano, Task 9).

Cada critério de aceite do incremento 1 precisa de pelo menos um teste marcado com
`@pytest.mark.ac("AC-xx")` que tenha PASSADO nesta execução. Se faltar algum, a sessão termina
com falha e lista os ids.

Quando o hook vale: só em execução completa. Isto é, sem `-k`, `--deselect`, `--lf`, `--sw`,
`--co`, sem arquivo/diretório/nodeid diferente de `testpaths` e com `-m` vazio ou exatamente
`-m ac`. Assim `pytest tests/domain/test_scene.py` ou `pytest -k algo` não quebram por AC
alheio, e `pytest -m ac` (o comando de evidência) continua exigindo os dez.
"""

from pathlib import Path

import pytest

INCREMENT_1_ACS = frozenset(
    {"AC-03", "AC-04", "AC-05", "AC-06", "AC-21", "AC-22", "AC-23", "AC-24", "AC-27", "AC-39"}
)


def _ids_of(item: pytest.Item) -> frozenset[str]:
    return frozenset(arg for m in item.iter_markers("ac") for arg in m.args)


def _opt(config, name: str):
    return getattr(config.option, name, None)


def is_full_run(config) -> bool:
    if any(_opt(config, n) for n in ("keyword", "deselect", "lf", "ff", "stepwise", "collectonly")):
        return False
    if _opt(config, "markexpr") not in ("", None, "ac"):
        return False
    given = list(_opt(config, "file_or_dir") or [])
    if not given:
        return True
    root = Path(config.rootpath)
    wanted = {(root / p).resolve() for p in (config.getini("testpaths") or [])}
    return bool(wanted) and {(Path.cwd() / a).resolve() for a in given} <= wanted


class ACTraceability:
    """Plugin por sessão: o estado mora na instância, então sessões aninhadas não se misturam."""

    def __init__(self, config) -> None:
        self.config = config
        self.marked: dict[str, frozenset[str]] = {}
        self.passed: set[str] = set()

    def pytest_collection_modifyitems(self, items):
        self.marked = {item.nodeid: _ids_of(item) for item in items}

    def pytest_runtest_logreport(self, report):
        if report.when == "call" and report.passed:
            self.passed.add(report.nodeid)

    def missing(self) -> list[str]:
        covered: set[str] = set()
        for nodeid in self.passed:
            covered |= self.marked.get(nodeid, frozenset())
        return sorted(INCREMENT_1_ACS - covered)

    def _enforced(self, exitstatus) -> bool:
        ok = exitstatus in (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED)
        return ok and is_full_run(self.config)

    def pytest_sessionfinish(self, session, exitstatus):
        if self._enforced(exitstatus) and self.missing():
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter, exitstatus):
        missing = self.missing() if self._enforced(exitstatus) else []
        if missing:
            terminalreporter.section("rastreabilidade AC x teste", sep="=", red=True)
            terminalreporter.write_line(
                "AC sem teste marcado e aprovado: " + ", ".join(missing), red=True
            )


# Opt-out explícito: `pytest -p no:ac-traceability` desliga o hook (o plugin é registrado com esse nome).
def register(config) -> None:
    config.pluginmanager.register(ACTraceability(config), "ac-traceability")
