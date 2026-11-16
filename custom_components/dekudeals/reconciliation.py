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
    """Build a no-deletion plan; ambiguous duplicate count changes need review."""
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
            {
                **item,
                "identity": identity,
                "fingerprint": _fingerprint_for(item, identity),
            }
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
            existing_groups[item["source_identity"]].append(
                {"copy_id": copy_id, **item}
            )

    all_identities = set(imported_groups) | set(existing_groups)
    for identity in all_identities:
        incoming = imported_groups.get(identity, [])
        existing = existing_groups.get(identity, [])

        if not existing:
            creates.extend(incoming)
            continue

        if not incoming:
            for item in existing:
                if item.get("collection_present") is False and not item.get("needs_review"):
                    continue
                updates[item["copy_id"]] = {
                    "collection_present": False,
                    "needs_review": True,
                    "review_reason": "missing_from_collection",
                }
            continue

        if len(incoming) < len(existing) or any(
            item.get("needs_review") for item in existing
        ):
            ambiguous.update(item["copy_id"] for item in existing)
            for item in existing:
                updates[item["copy_id"]] = {
                    "needs_review": True,
                    "review_reason": "duplicate_count_changed",
                }
            continue

        if len(incoming) > len(existing) and not all(
            item.get("match_confirmed") is True
            and item.get("collection_present") is True
            for item in existing
        ):
            ambiguous.update(item["copy_id"] for item in existing)
            for item in existing:
                updates[item["copy_id"]] = {
                    "needs_review": True,
                    "review_reason": "duplicate_count_changed",
                }
            continue

        # Explicitly confirmed copies can be matched and any additional rows
        # created; IDs, loans, and private notes on existing copies are kept.
        ordered_existing = sorted(existing, key=lambda row: row["copy_id"])
        ordered_incoming = sorted(incoming, key=lambda row: row["fingerprint"])
        for old, new in zip(ordered_existing, ordered_incoming):
            updates[old["copy_id"]] = {
                "source_fingerprint": new["fingerprint"],
                "collection_present": True,
                "needs_review": False,
                "review_reason": None,
                "image": new.get("image"),
                "description": new.get("description"),
            }
        if len(ordered_incoming) > len(ordered_existing):
            creates.extend(ordered_incoming[len(ordered_existing):])

    return {
        "updates": updates,
        "creates": creates,
        "ambiguous": ambiguous,
    }
