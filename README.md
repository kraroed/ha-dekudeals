# DekuDeals Home Assistant

A Home Assistant custom integration for synchronizing a public DekuDeals collection and tracking physical game copies and loans.

> **Development status:** Early development, not a release. Live collection fetching uses the public JSON export available by appending `.json` to a DekuDeals collection URL. This is an export endpoint, not a documented official API, so it may change without notice.

## Features implemented

- Fetch a public DekuDeals collection JSON export automatically.
- Refresh the collection every six hours, with a manual refresh service.
- Preserve duplicate rows and original order.
- Normalize missing platforms to `Unknown`.
- Collection count sensors for all games, Switch, Switch 2, physical, and digital games.
- Persistent local physical-copy inventory, separate from the online collection.
- Unique IDs for duplicate physical copies.
- Manual physical-copy registration.
- Lending and return tracking with permanent history.
- Optional due dates and overdue tracking (due today is not overdue).
- Conservative duplicate-aware reconciliation. Uncertain count changes are flagged for review; copies and loan records are never automatically deleted.
- Optional saved JSON export fallback for use when the public endpoint is unavailable.

## Collection setup

Add **DekuDeals** from Settings → Devices & services and enter your public collection URL, for example:

`https://www.dekudeals.com/collection/your-collection-id`

The integration requests the corresponding `.json` export. No DekuDeals password or account credentials are required. If the endpoint is unavailable during setup, you can optionally provide a saved JSON export as a fallback.

To update manually, call `dekudeals.refresh_collection`. Automatic refresh runs every six hours. The optional fallback export can be replaced or cleared in the integration's Configure / Options flow.

## Expected JSON shape

The public export is expected to contain a JSON object with an `items` array. Each row may include `name`, `link`, `added_at`, `format`, `platform`, and `note`.

```json
{
  "items": [
    {
      "name": "Example Game",
      "link": "https://www.dekudeals.com/items/example-game",
      "added_at": "2026-01-01",
      "format": "physical",
      "platform": "Switch"
    }
  ]
}
```

Rows are not deduplicated. Each physical row represents a separate copy.

## Sensors

Collection sensor names:
- Games
- Switch Games
- Switch 2 Games
- Physical Games
- Digital Games

Physical inventory sensor names:
- Games In Possession
- Games Lent Out
- Games Overdue
- Total Physical Copies
- Active Game Loans
- Game Lending History
- Inventory Needs Review
- Unmatched Physical Games

Home Assistant generates entity IDs from the configured entity and device names; use the entity IDs shown in your instance.

Sensor attributes expose bounded lists (up to 500 records) and a truncation flag. The lending-history sensor exposes the 20 most recent events while the full history remains stored locally.

## Services

All services accept optional `config_entry_id` when multiple collections are configured.

- `dekudeals.register_copy`: register a physical copy not represented by the export (`game`, optional `platform`, `notes`).
- `dekudeals.lend_game`: lend a copy (`copy_id`, `borrower`, optional `due_date` in YYYY-MM-DD, `notes`).
- `dekudeals.return_game`: return a loan (`copy_id`).
- `dekudeals.update_inventory`: update copy notes (`copy_id`, `notes`).
- `dekudeals.resolve_inventory_match`: resolve a review item (`copy_id`, `resolution`: `present`, `not_present`, or `manual`).
- `dekudeals.refresh_collection`: request an immediate live refresh and reconciliation.

Only physical copies can be lent. Digital collection entries never enter the physical inventory.

## Installation

This integration is not yet published in HACS. For development, copy `custom_components/dekudeals` into `config/custom_components/`, restart Home Assistant, then add the integration from Settings → Devices & services.

## Development and validation

GitHub Actions run unit tests, Python compilation, Home Assistant hassfest, and HACS validation. HACS validation still needs repository metadata, a license, and branding assets before the repository is ready for HACS publication.
