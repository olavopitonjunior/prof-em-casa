import json
from pathlib import Path

import pytest
from app.content.loader import load_content, public_item
from app.domain.division.errors import DomainError
from app.domain.division.task import TaskSpec


def test_items_have_spec_values():
    c = load_content()
    assert {
        k: (i.task.dividend, i.task.divisor, i.private.quotient) for k, i in c.items.items()
    } == {
        "demo-12-4": (12, 4, 3),
        "guided-24-4": (24, 4, 6),
        "transfer-20-5": (20, 5, 4),
    }


def test_public_item_hides_answers():
    c = load_content()
    for key in ("guided-24-4", "transfer-20-5"):
        dumped = json.dumps(public_item(c.items[key]), ensure_ascii=False)
        assert "private" not in dumped and "quotient" not in dumped
    assert '"6"' not in json.dumps(public_item(c.items["guided-24-4"]))
    assert public_item(c.items["demo-12-4"])["demo_expression"] == "12 ÷ 4 = 3"


def test_engine_limits_rejected():  # dividend<=30, divisor 2..6, divisão exata
    for bad in [(32, 4), (24, 7), (25, 4), (24, 1)]:
        with pytest.raises(DomainError) as e:
            TaskSpec(dividend=bad[0], divisor=bad[1], unit="peças")
        assert e.value.code == "UNSUPPORTED_CONTENT"


def test_no_resto_in_learner_copy():
    raw = Path("content/division-sharing-v1/interventions.json").read_text().lower()
    assert "resto" not in raw


# --- load_content: conteúdo corrompido vira UNSUPPORTED_CONTENT -------------------------------

SRC = Path("content/division-sharing-v1")


def _bad_package(tmp_path: Path, filename: str, mutate) -> Path:
    """Copia o pacote para tmp_path/division-sharing-v1 e aplica `mutate(texto) -> texto`."""
    target = tmp_path / "division-sharing-v1"
    target.mkdir()
    for f in SRC.iterdir():
        (target / f.name).write_bytes(f.read_bytes())
    path = target / filename
    path.write_text(mutate(path.read_text(encoding="utf-8")), encoding="utf-8")
    return tmp_path


def _items(text: str) -> list:
    return json.loads(text)


def _dump(obj) -> str:
    return json.dumps(obj)


def test_load_content_from_a_custom_base_dir(tmp_path):
    base = _bad_package(tmp_path, "items.json", lambda t: t)
    assert set(load_content(base_dir=base).items) == {"demo-12-4", "guided-24-4", "transfer-20-5"}


@pytest.mark.parametrize(
    ("filename", "mutate"),
    [
        ("items.json", lambda t: _dump([{**_items(t)[0], "x": 1}, *_items(t)[1:]])),  # extra
        (
            "items.json",
            lambda t: _dump(
                [
                    {**_items(t)[0], "task": {**_items(t)[0]["task"], "dividend": True}},
                    *_items(t)[1:],
                ]
            ),
        ),  # bool
        (
            "items.json",
            lambda t: _dump([{k: v for k, v in _items(t)[0].items() if k != "item_id"}]),
        ),  # KeyError
        ("items.json", lambda t: "{"),  # JSONDecodeError
        ("items.json", lambda t: _dump({"not": "a list"})),  # estrutura errada
        ("items.json", lambda t: _dump([1, 2])),  # item que não é objeto
        ("demonstration.json", lambda t: _dump({"item_id": "demo-12-4"})),
        ("interventions.json", lambda t: _dump(["x"])),
        ("interventions.json", lambda t: _dump({"code": 1})),
    ],
)
def test_corrupt_content_raises_unsupported_content(tmp_path, filename, mutate):
    base = _bad_package(tmp_path, filename, mutate)
    with pytest.raises(DomainError) as e:
        load_content(base_dir=base)
    assert e.value.code == "UNSUPPORTED_CONTENT"
    assert e.value.__cause__ is not None  # encadeada com `from`


def test_missing_file_and_invalid_utf8_raise_unsupported_content(tmp_path):
    base = _bad_package(tmp_path, "items.json", lambda t: t)
    (base / "division-sharing-v1" / "interventions.json").unlink()
    with pytest.raises(DomainError) as e:
        load_content(base_dir=base)
    assert e.value.code == "UNSUPPORTED_CONTENT" and isinstance(
        e.value.__cause__, FileNotFoundError
    )
    (base / "division-sharing-v1" / "interventions.json").write_bytes(b"\xff\xfe")
    with pytest.raises(DomainError) as e:
        load_content(base_dir=base)
    assert e.value.code == "UNSUPPORTED_CONTENT" and isinstance(
        e.value.__cause__, UnicodeDecodeError
    )


def test_duplicate_item_ids_are_rejected(tmp_path):
    base = _bad_package(tmp_path, "items.json", lambda t: _dump([*_items(t), _items(t)[0]]))
    with pytest.raises(DomainError) as e:
        load_content(base_dir=base)
    assert e.value.code == "UNSUPPORTED_CONTENT" and "duplicate" in (e.value.detail or "")
