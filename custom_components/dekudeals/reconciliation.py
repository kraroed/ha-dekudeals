"""Conservative duplicate-aware reconciliation for physical inventory."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any


def _normalize(value: Any) -> str:
    """Normalize a value for matching without changing its displayed form."""
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _identity_for(item: dict[str, Any]) -> str:
    """Return stable identity based on title, platform, format, and source link."""
    identity = {
        "name": _normalize(item.get("name")),
        "platform": _normalize(item.get("platform") or "Unknown"),
        "format": _normalize(item.get("format")),
        "link": _normalize(item.get("link")).rstrip("/"),
    }
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def _fingerprint_for(item: dict[str, Any], identity: str) -> str:
    """Return a source snapshot fingerprint; mutable date is not identity."""
    payload = json.dumps(
        {"identity": identity, "added_at": item.get("added_at")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def build_reconciliation_plan(
    imported_items: list[dict[str, Any]], copies: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Build a no-deletion plan; never guess among ambiguous duplicate rows."""
    imported_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    existing_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    updates: dict[str, dict[str, Any]] = {}
    creates: list[dict[str, Any]] = []
    ambiguous: set[str] = set()

    for item in imported_items:
        if item.get("format") != "physical":
            continue
        identity = _identity_for(item)
        imported_groups[identity].append(
            {**item, "identity": identity, "fingerprint": _fingerprint_for(item, identity)}
        )

    for copy_id, item in copies.items():
        if (
            item.get("source") == "dekudeals"
            and item.get("source_identity")
            and not (
                item.get("collection_present") is False
                and not item.get("needs_review")
            )
        ):
            existing_groups[item["source_identity"]].append({"copy_id": copy_id, **item})

    def apply_match(old: dict[str, Any], new: dict[str, Any]) -> None:
        changes = {
            "source_fingerprint": new["fingerprint"],
            "collection_present": True,
            "needs_review": False,
            "review_reason": None,
        }
        for field in ("image", "description"):
            if new.get(field):
                changes[field] = new[field]
        updates[old["copy_id"]] = changes

    for identity in set(imported_groups) | set(existing_groups):
        incoming = imported_groups.get(identity, [])
        existing = existing_groups.get(identity, [])

        if not existing:
            creates.extend(incoming)
            continue

        if not incoming:
            for old in existing:
                updates[old["copy_id"]] = {
                    "collection_present": False,
                    "needs_review": True,
                    "review_reason": "missing_from_collection",
                }
            continue

        # Once a group needs human review, do not silently clear that decision
        # or reassign any of its physical copies during a later refresh.
        if any(old.get("needs_review") for old in existing):
            ambiguous.update(old["copy_id"] for old in existing)
            for old in existing:
                updates[old["copy_id"]] = {
                    "needs_review": True,
                    "review_reason": old.get("review_reason") or "duplicate_count_changed",
                }
            continue

        # First preserve exact source-row associations. Sorting IDs against
        # fingerprints is not a match: it can swap distinct copies' identities.
        old_by_fingerprint: dict[str, list[dict[str, Any]]] = defaultdict(list)
        new_by_fingerprint: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for old in existing:
            fingerprint = old.get("source_fingerprint")
            if isinstance(fingerprint, str) and fingerprint:
                old_by_fingerprint[fingerprint].append(old)
        for new in incoming:
            new_by_fingerprint[new["fingerprint"]].append(new)

        # When an identical source-row fingerprint shrinks, there is no safe
        # way to know which physical copy remains. Growth is handled below:
        # creating an extra copy is allowed only after explicit confirmation.
        changed_duplicate_bucket = any(
            old_by_fingerprint.get(fingerprint)
            and new_by_fingerprint.get(fingerprint)
            and len(old_by_fingerprint[fingerprint]) > len(new_by_fingerprint[fingerprint])
            for fingerprint in set(old_by_fingerprint) | set(new_by_fingerprint)
        )
        if changed_duplicate_bucket:
            ambiguous.update(old["copy_id"] for old in existing)
            for old in existing:
                updates[old["copy_id"]] = {
                    "needs_review": True,
                    "review_reason": "duplicate_count_changed",
                }
            continue

        remaining_old: list[dict[str, Any]] = []
        remaining_new: list[dict[str, Any]] = []
        for fingerprint in set(old_by_fingerprint) | set(new_by_fingerprint):
            old_rows = sorted(old_by_fingerprint.get(fingerprint, []), key=lambda row: row["copy_id"])
            new_rows = new_by_fingerprint.get(fingerprint, [])
            matched_count = min(len(old_rows), len(new_rows))
            for old, new in zip(old_rows[:matched_count], new_rows[:matched_count]):
                apply_match(old, new)
            remaining_old.extend(old_rows[matched_count:])
            remaining_new.extend(new_rows[matched_count:])

        # One unmatched old row and one unmatched new row is an unambiguous
        # changed snapshot. Multiple residual candidates are not.
        if len(remaining_old) == 1 and len(remaining_new) == 1:
            apply_match(remaining_old[0], remaining_new[0])
            continue

        if not remaining_old:
            # New duplicate copies are safe only after every existing copy in
            # this identity group was explicitly confirmed present.
            if remaining_new and all(
                old.get("match_confirmed") is True
                and old.get("collection_present") is True
                for old in existing
            ):
                creates.extend(remaining_new)
            elif remaining_new:
                ambiguous.update(old["copy_id"] for old in existing)
                for old in existing:
                    updates[old["copy_id"]] = {
                        "needs_review": True,
                        "review_reason": "duplicate_count_changed",
                    }
            continue

        if not remaining_new:
            # Exact matches remain safely associated; only disappeared rows
            # are marked for review and retained in inventory.
            for old in remaining_old:
                ambiguous.add(old["copy_id"])
                updates[old["copy_id"]] = {
                    "needs_review": True,
                    "review_reason": "duplicate_count_changed",
                }
            continue

        # More than one possible pairing: retain every copy and ask the user.
        ambiguous.update(old["copy_id"] for old in remaining_old)
        for old in remaining_old:
            updates[old["copy_id"]] = {
                "needs_review": True,
                "review_reason": "duplicate_count_changed",
            }

    return {"updates": updates, "creates": creates, "ambiguous": ambiguous}
