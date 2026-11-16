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
        "match_confirmed": False,
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


def test_extra_duplicate_is_created_only_after_explicit_confirmation():
    identity = build_reconciliation_plan([_item()], {})["creates"][0]["identity"]
    copies = {"copy-a": {**_copy("copy-a", identity), "match_confirmed": True}}

    plan = build_reconciliation_plan([_item(), _item()], copies)

    assert len(plan["creates"]) == 1
    assert plan["ambiguous"] == set()


def test_confirmed_not_present_copy_is_not_rematched():
    identity = build_reconciliation_plan([_item()], {})["creates"][0]["identity"]
    copy = {
        **_copy("copy-a", identity),
        "collection_present": False,
        "match_confirmed": True,
    }

    plan = build_reconciliation_plan([_item()], {"copy-a": copy})

    assert len(plan["creates"]) == 1
    assert plan["updates"] == {}



def test_confirmed_not_present_copy_is_not_recreated_on_repeated_refresh():
    """A manually rejected match must not cause duplicate copies every refresh."""
    identity = build_reconciliation_plan([_item()], {})["creates"][0]["identity"]
    rejected = {
        **_copy("copy-rejected", identity),
        "collection_present": False,
        "match_confirmed": True,
    }

    first = build_reconciliation_plan([_item()], {"copy-rejected": rejected})
    assert len(first["creates"]) == 1
    assert first["updates"] == {}

    created = first["creates"][0]
    replacement = _copy("copy-replacement", identity)
    replacement.update(
        source_fingerprint=created["fingerprint"],
        collection_present=True,
        match_confirmed=False,
    )
    second = build_reconciliation_plan(
        [_item()], {"copy-rejected": rejected, "copy-replacement": replacement}
    )

    assert second["creates"] == []
    assert second["ambiguous"] == set()
    assert second["updates"]["copy-replacement"]["collection_present"] is True


def test_confirmed_present_copy_is_stable_across_refreshes():
    identity = build_reconciliation_plan([_item()], {})["creates"][0]["identity"]
    confirmed = {
        **_copy("copy-confirmed", identity),
        "collection_present": True,
        "match_confirmed": True,
    }

    first = build_reconciliation_plan([_item()], {"copy-confirmed": confirmed})
    assert first["creates"] == []
    assert first["ambiguous"] == set()

    second = build_reconciliation_plan([_item()], {"copy-confirmed": confirmed})
    assert second["creates"] == []
    assert second["ambiguous"] == set()


def test_removed_collection_row_flags_copy_without_overwriting_active_loan():
    identity = build_reconciliation_plan([_item()], {})["creates"][0]["identity"]
    loan = {
        "borrower": "Alex",
        "lent_at": "2026-01-01T00:00:00+00:00",
        "due_date": "2026-01-10",
        "notes": "Keep this loan",
    }
    copy = _copy("copy-on-loan", identity, loan)

    plan = build_reconciliation_plan([], {"copy-on-loan": copy})

    assert plan["creates"] == []
    assert plan["updates"]["copy-on-loan"] == {
        "collection_present": False,
        "needs_review": True,
        "review_reason": "missing_from_collection",
    }
    assert copy["active_loan"] == loan
