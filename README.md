# DekuDeals Home Assistant

A Home Assistant custom integration for synchronizing a public DekuDeals collection and tracking physical game copies and loans.

**Release: 0.4.8**

Version 0.4.8 serves TheGamesDB front-cover images through a signed, same-origin Home Assistant endpoint. This avoids direct CDN image requests from the Home Assistant app while restricting the proxy to approved HTTPS front-cover URLs. The proxy rejects redirects, unexpected content types, and oversized responses. Collection data, metadata cache, and physical inventory are preserved.

Version 0.4.7 improves TheGamesDB front-cover selection and adds the `dekudeals.refresh_artwork` service to retry cached artwork lookups on demand. The artwork refresh preserves collection data, physical inventory, descriptions, and previously verified covers. Metadata enrichment now processes up to 50 items per refresh. TheGamesDB HTTP errors are logged with their status code without exposing API credentials.

Version 0.4.3 excludes large collection and inventory list attributes from Recorder history. These attributes remain available in live entity state for the Lovelace card, while count values and small status attributes continue to be recorded.

Version 0.4.2 retries previously missing cover artwork once when a TheGamesDB API key is added, instead of waiting for the normal seven-day missing-art retry window.

## Features

- Import a public DekuDeals collection automatically.
- Refresh the collection every six hours, or on demand.
- Preserve duplicate collection rows and their original order.
- Normalize missing platform values to `Unknown`.
- Enrich collection rows with verified portrait artwork, the actual item-page Description text, and DLC classification from public DekuDeals item titles and descriptions.
- Optional TheGamesDB artwork lookup: when an API key is configured, the integration requests the exact game title and console and accepts only images explicitly marked `boxart` / `front` with portrait dimensions. No approximate title or cross-console matches are accepted.
- Serve approved TheGamesDB front covers through a signed same-origin endpoint for Home Assistant dashboards.
- Retry one provider lookup for previously cached missing covers after an API key is added; unsuccessful lookups retain the normal seven-day retry interval.
- Cache game metadata locally using a fresh versioned cache key so upgrades do not require an unsupported Home Assistant storage migration; fetch at most 50 missing item pages per collection refresh with limited concurrency to avoid excessive requests.
- Collection count sensors for full games, DLC items, Switch, Switch 2, physical games, and digital games. DLC does not inflate full-game counts.
- Persistent local physical-copy inventory, separate from the online collection.
- Unique IDs for duplicate physical copies.
- Register physical copies manually.
- Track loans, borrower names, optional due dates, and returns.
- Preserve a permanent lending and return history.
- Track overdue loans; a game due today is not overdue.
- Reconcile collection changes conservatively. Ambiguous duplicate-count changes are flagged for review; existing copies, loans, and history are not automatically deleted.
- Optionally save a JSON export as a fallback if the public endpoint is unavailable.

## Installation

### HACS

1. Open HACS in Home Assistant.
2. Open the integrations section and use the menu to add a custom repository.
3. Enter `https://github.com/kraroed/ha-dekudeals` and select **Integration** as the category.
4. Find **DekuDeals** and install it.
5. Restart Home Assistant.

### Home Assistant Marketplace

On Home Assistant versions that include Marketplace, open **Settings → Marketplace**, choose **Add from link**, and enter `kraroed/ha-dekudeals`. The repository must still meet the Marketplace's custom-repository requirements. Restart Home Assistant after installation.

### Manual installation

Copy `custom_components/dekudeals` into `<config>/custom_components/dekudeals`, then restart Home Assistant.

## Configuration

1. In Home Assistant, open **Settings → Devices & services → Add integration**.
2. Search for **DekuDeals**.
3. Enter the console/platform exactly as it appears in your DekuDeals export (for example `Switch`, `Switch 2`, or `PlayStation 5`). Choose `All Platforms` to include the entire collection.
4. Enter your public collection URL, for example:

   `https://www.dekudeals.com/collection/your-collection-id`

You can add the same collection URL more than once, using a different platform each time. Each entry has its own sensors, physical-copy inventory, loans, history, and refresh operation. The original Switch entry keeps its existing identity and stored inventory when upgraded. The integration requests the matching `.json` export automatically. You can optionally paste a saved JSON export during setup as an offline fallback. The integration prefers live data and uses the saved export only when the live request fails.

To replace or clear the fallback later, open the integration's **Configure** options. You can also add an optional [TheGamesDB API key](https://api.thegamesdb.net/) there to enable front-box-art fallback lookups. Without a key, the integration uses only verified portrait artwork found on the DekuDeals item page. After adding a key, refresh the collection to retry previously missing covers; the provider is checked once for those cached misses, and unsuccessful checks are not repeated on every refresh.

## Supported export format

The export can be either a JSON object containing an `items` array or a top-level JSON array. Each row should contain an item `name`; optional fields include `link`, `added_at`, `format`, `platform`, and `note`. Rows are not deduplicated. Each physical row represents a separate collection copy.

## Sensors

Collection sensor attributes expose bounded lists (up to 500 records) and include a truncation flag. Collection `items` include `image`, `description`, `item_type` (`game` or `dlc`), and `parent_game` when available. TheGamesDB front-cover URLs are exposed as signed same-origin Home Assistant URLs; other image sources are left unchanged. Large list attributes are excluded from Recorder history, but remain available live to the Lovelace card.

## Services

All services accept an optional `config_entry_id` when multiple collections are configured.

- `dekudeals.refresh_collection` — fetch the latest public export and reconcile inventory.
- `dekudeals.refresh_artwork` — retry cached artwork lookups without clearing collection data or physical inventory.
- `dekudeals.register_copy`, `dekudeals.lend_game`, `dekudeals.return_game`, `dekudeals.update_inventory`, and `dekudeals.resolve_inventory_match` — manage physical copies and lending history.

## Data and privacy

The integration requests the public collection export and eligible public item pages over HTTPS. It does not ask for or store your DekuDeals password. Game metadata and physical inventory are cached locally in Home Assistant. The artwork endpoint is unauthenticated for browser image compatibility, but each image URL requires an unguessable per-entry signature and is restricted to TheGamesDB's approved front-cover path. Redirects are disabled and response size and image content type are checked.

## Development

The repository runs unit tests, Python compilation, Home Assistant hassfest validation, and HACS validation in GitHub Actions.
