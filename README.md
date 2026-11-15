# DekuDeals Home Assistant

A Home Assistant custom integration for importing a Deku Deals collection and tracking physical game copies.

> Early development: this first repository implementation establishes the collection-import foundation. Automatic live synchronization with Deku Deals and the physical inventory/lending workflow are being added in subsequent commits. Do not treat this version as a release.

## Current foundation

- Import a Deku Deals JSON collection export during setup.
- Preserve duplicate rows (each physical copy remains a separate collection record).
- Normalize missing platform values to `Unknown`.
- Expose collection counts and a bounded list of game records as sensors.
- Keep the imported source data separate from the planned local inventory store.

## Import format

The integration accepts a JSON object containing an `items` array. Each row may include `name`, `link`, `added_at`, `format`, `platform`, and `note`.

## Installation

This is not yet published in HACS. For development, copy `custom_components/dekudeals` into `config/custom_components/`, restart Home Assistant, then add **DekuDeals** from Settings → Devices & services.

## Development status

The next implementation stages are persistent physical-copy inventory, lending/returns with permanent history, safe duplicate-aware reconciliation, service actions, tests, and HACS/HA validation.
