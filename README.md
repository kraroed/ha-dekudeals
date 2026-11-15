# DekuDeals Home Assistant

A Home Assistant custom integration for importing a DekuDeals collection and tracking physical game copies and loans.

> **Development status:** Early development, not a release. The current implementation imports a DekuDeals JSON export supplied during setup or through the integration options. It does not yet automatically fetch the live collection from DekuDeals.

## Features implemented

- Import a JSON collection export with an `items` array.
- Preserve duplicate collection rows and original order.
- Normalize missing platforms to `Unknown`.
- Collection count sensors for all games, Switch, Switch 2, physical, and digital games.
- Persistent local physical-copy inventory, separate from the imported collection.
- Unique IDs for duplicate physical copies.
- Manual physical-copy registration.
- Lending and return tracking with permanent history.
- Optional due dates and overdue tracking (due today is not overdue).
- Conservative duplicate-aware reconciliation. Uncertain count changes are flagged for review; copies and loan records are never automatically deleted.
- Replace the imported export through the integration's Configure / Options flow.

## Import format

The integration accepts a JSON object containing an `items` array. Each row may include `name`, `link`, `added_at`, `format`, `platform`, and `note`.

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

## Installation

This integration is not yet published in HACS. For development, copy `custom_components/dekudeals` into `config/custom_components/`, restart Home Assistant, then add **DekuDeals** from Settings → Devices & services.

During setup, enter your collection URL and paste the JSON export. To import a newer export later, open the integration's Configure option and replace the JSON. The integration reloads and reconciles the new snapshot while retaining local inventory and lending history.

## Sensors

Collection:
- `sensor.deku_deals_games`
- `sensor.deku_deals_switch_games`
- `sensor.deku_deals_switch_2_games`
- `sensor.deku_deals_physical_games`
- `sensor.deku_deals_digital_games`

Physical inventory:
- `sensor.deku_deals_games_in_possession`
- `sensor.deku_deals_games_lent_out`
- `sensor.deku_deals_games_overdue`
- `sensor.deku_deals_total_physical_copies`
- `sensor.deku_deals_active_game_loans`
- `sensor.deku_deals_game_lending_history`
- `sensor.deku_deals_inventory_needs_review`
- `sensor.deku_deals_unmatched_physical_games`

Sensor attributes expose bounded lists (up to 500 records) and a truncation flag. The lending-history sensor exposes the 20 most recent events while the full history remains stored locally.

## Services

All services accept optional `config_entry_id` when multiple collections are configured.

- `dekudeals.register_copy`: register a physical copy not represented by the export (`game`, optional `platform`, `notes`).
- `dekudeals.lend_game`: lend a copy (`copy_id`, `borrower`, optional `due_date` in YYYY-MM-DD, `notes`).
- `dekudeals.return_game`: return a loan (`copy_id`).
- `dekudeals.update_inventory`: update copy notes (`copy_id`, `notes`).
- `dekudeals.resolve_inventory_match`: resolve a review item (`copy_id`, `resolution`: `present`, `not_present`, or `manual`).
- `dekudeals.refresh_collection`: reload the currently stored export and re-run reconciliation. This is not a live website fetch.

Only physical copies can be lent. Digital collection entries never enter the physical inventory.

## Development and validation

The GitHub Actions workflow currently runs parser, reconciliation, and inventory unit tests. Full Home Assistant runtime tests, Home Assistant validation, HACS validation, branding, and live DekuDeals synchronization remain outstanding.
