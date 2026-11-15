"""Tests for safe physical inventory reconciliation."""

from custom_components.dekudeals.reconciliation import build_reconciliation_plan


def _item(name="Game", added_at="2026-01-01"):
    return {
        "name": name,
        "format": "physical",
        "platform": "Switch",
        "link": "https://www.dekudeals.com/items/game",
        "added_at": added_at,
    }


def _copy(copy_id, identity, loan=None):
    return {
        "copy_id": copy_id,
        "game": "Game",
        "platform": "Switch",
        "format": "physical",
        "source": "dekudeals",
        "source_identity": identity,
        "source_fingerprint": "old",
        "collection_present": True,
        "needs_review": False,
        "review_reason": None,
        "notes": "keep my notes",
        "active_loan": loan,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_new_physical_item_creates_one_copy():
    plan = build_reconciliation_plan([_item()], {})

    assert len(plan["creates"]) == 1
    assert plan["creates"][0]["name"] == "Game"


def test_digital_items_are_ignored():
    digital = {**_item(), "format": "digital"}
    plan = build_reconciliation_plan([digital], {})

    assert plan["creates"] == []


def test_equal_duplicate_groups_preserve_copy_ids_and_loan_state():
    incoming = [_item(), _item()]
    identity = build_reconciliation_plan(incoming, {})["creates"][0]["identity"]
    copies = {
        "copy-a": _copy("copy-a", identity, {"borrower": "Alex"}),
        "copy-b": _copy("copy-b", identity),
    }

    plan = build_reconciliation_plan(incoming, copies)

    assert plan["creates"] == []
    assert set(plan["updates"]) == {"copy-a", "copy-b"}
    assert plan["updates"]["copy-a"]["needs_review"] is False


def test_duplicate_count_change_is_flagged_without_guessing():
    identity = build_reconciliation_plan([_item()], {})["creates"][0]["identity"]
    copies = {"copy-a": _copy("copy-a", identity)}

    plan = build_reconciliation_plan([_item(), _item()], copies)

    assert plan["creates"] == []
    assert plan["ambiguous"] == {"copy-a"}
    assert plan["updates"]["copy-a"]["review_reason"] == "duplicate_count_changed"


def test_missing_collection_item_is_retained_for_review():
    identity = build_reconciliation_plan([_item()], {})["creates"][0]["identity"]
    copies = {"copy-a": _copy("copy-a", identity)}

    plan = build_reconciliation_plan([], copies)

    assert plan["creates"] == []
    assert plan["updates"]["copy-a"]["collection_present"] is False
    assert plan["updates"]["copy-a"]["needs_review"] is True


def test_manual_copies_are_never_touched_by_reconciliation():
    manual = {**_copy("manual", "ignored"), "source": "manual"}
    plan = build_reconciliation_plan([], {"manual": manual})

    assert plan["updates"] == {}
    assert plan["creates"] == []
