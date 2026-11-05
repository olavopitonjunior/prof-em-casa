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
