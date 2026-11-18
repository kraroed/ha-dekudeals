# DekuDeals Home Assistant

A Home Assistant custom integration for synchronizing a public DekuDeals collection and tracking physical game copies and loans.

**Release: 0.4.21**

Version 0.4.21 improves artwork coverage for DLC and makes TheGamesDB lookup outcomes diagnosable. DLC parent artwork inheritance now resolves missing or `Unknown` item platforms using the configured console, and only reuses a verified parent cover from the same platform. TheGamesDB lookups now expose explicit per-item statuses for missing API keys, platform mapping, provider/network failures, exact-title misses, and covers that fail verification. Transient failures remain eligible for retry, while definitive misses retain their retry interval. The Artwork URL Coverage sensor now includes bounded counts and samples grouped by lookup status.

Version 0.4.20 adds persistent Home Assistant notifications for `dekudeals.refresh_artwork`. The notification updates when the service is called, when the forced refresh starts, and when it completes or fails, so progress is visible without searching the logs.

Version 0.4.19 adds service-boundary diagnostics for `dekudeals.refresh_artwork`, logging when the service is received, which config entry is selected, whether the refresh completes, and any exception raised by the handler.

Version 0.4.18 adds exact-title, exact-platform TheGamesDB lookups for DLC parent games that are not present in the collection. Verified parent front covers are cached and reused across matching DLC, with bounded lookup volume and retry intervals. Existing verified standalone DLC artwork retains priority.

Version 0.4.17 adds detailed missing-artwork diagnostics, including counts and sample titles grouped by reason. Version 0.4.16 fixes a missing import that caused metadata enrichment to fail when applying verified parent-game artwork to DLC. Version 0.4.15 introduced conservative artwork inheritance: DLC can reuse a verified parent game's cover only when the DekuDeals item page explicitly identifies the parent. Standalone verified DLC covers retain priority, and inherited artwork is marked with `artwork_inherited: true`.

Version 0.4.14 adds the Artwork URL Coverage diagnostic sensor, reports its value as a Home Assistant percentage measurement, and retries transient TheGamesDB lookup failures on the next collection refresh instead of suppressing them for seven days. Definitive no-match lookups retain the normal seven-day retry interval.

Version 0.4.13 fixes incomplete artwork downloads by reading the complete upstream image stream in bounded chunks, enforcing the 8 MiB limit during streaming, and asking upstream servers and caches not to transform the original image bytes. This preserves sharp, fully loaded cover art in Lovelace.

Version 0.4.12 fixes the artwork proxy's Home Assistant request context so signed artwork URLs are served correctly.

Version 0.4.11 adds in-app artwork diagnostics to help distinguish provider/CDN failures from Lovelace display issues.

Version 0.4.10 restores TheGamesDB artwork through the signed, same-origin Home Assistant proxy. The proxy follows up to three redirects only when every destination remains an approved HTTPS TheGamesDB front-cover URL. It validates image content types and enforces an 8 MiB response limit. Collection data, cached artwork metadata, physical inventory, loans, and lending history are preserved.

Version 0.4.8 serves TheGamesDB front-cover images through a signed, same-origin Home Assistant endpoint. This avoids direct CDN image requests from the Home Assistant app while restricting the proxy to approved HTTPS front-cover URLs. Redirects are disabled, and image content type and response size are checked. The original cached image URLs, collection data, and physical inventory remain unchanged.

Version 0.4.7 improves TheGamesDB front-cover selection and adds the `dekudeals.refresh_artwork` service to retry cached artwork lookups on demand. The artwork refresh preserves collection data, physical inventory, descriptions, and previously verified covers. Metadata enrichment now processes up to 50 items per refresh. TheGamesDB HTTP errors are logged with their status code without exposing API credentials.

Version 0.4.3 excludes large collection and inventory list attributes from Recorder history. These attributes remain available in live entity state for the Lovelace card, while count values and small status attributes continue to be recorded.

Version 0.4.2 retries previously missing cover artwork once when a TheGamesDB API key is added, instead of waiting for the normal seven-day missing-art retry window.

The integration reads the public JSON export available by appending `.json` to a DekuDeals collection URL. This is an undocumented export endpoint rather than a supported public API, so DekuDeals may change it without notice. No DekuDeals account credentials are requested or stored.

## Features

- Import a public DekuDeals collection automatically.
- Refresh the collection every six hours, or on demand.
- Preserve duplicate collection rows and their original order.
- Normalize missing platform values to `Unknown`.
- Enrich collection rows with verified portrait artwork, the actual item-page Description text, and DLC classification from public DekuDeals item titles and descriptions.
- Reuse a verified parent game's cover for DLC only when the item page explicitly identifies that parent and the DLC has no verified standalone cover; inherited artwork is marked with `artwork_inherited`. If the parent is not in the collection, perform a separate exact-title, exact-platform TheGamesDB lookup and cache the verified parent cover for reuse across matching DLC.
- Optional TheGamesDB artwork lookup: when an API key is configured, the integration requests the exact game title and console and accepts only images explicitly marked `boxart` / `front` with portrait dimensions. No approximate title or cross-console matches are accepted. External DLC-parent lookups are deduplicated by normalized parent title and platform, limited to 25 unique parents per refresh, cached for 30 days when verified and 7 days for definitive misses, and retried after transient failures.
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

The export can be either a JSON object containing an `items` array or a top-level JSON array. Each row should contain an item `name`; optional fields include `link`, `added_at`, `format`, `platform`, and `note`. The integration reads cover art from image metadata and extracts descriptions only from the visible Description section of eligible public DekuDeals item pages; it deliberately ignores social/meta descriptions that may contain sale copy. Items are classified as DLC using DekuDeals' “DLC for [game]” label, item title, and actual Description text (including DLC, downloadable content, season pass, expansion pack, and add-on markers). DLC is excluded from full-game, platform, and physical/digital game counts. Metadata lookups are limited to HTTPS `dekudeals.com/items/...` URLs and capped at 50 item pages per six-hour refresh. Successful artwork metadata is cached locally for 30 days; entries without verified artwork are retried after 7 days, except that adding a previously absent TheGamesDB API key triggers one immediate provider check on the next refresh. A missing or unavailable detail page does not prevent the collection itself from refreshing.

Example:

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

Rows are not deduplicated. Each physical row represents a separate collection copy.

## Sensors

### Collection

- **Games** — imported full-game rows, excluding DLC.
- **DLC Items** — imported DLC rows.
- **Artwork URL Coverage** — percentage of collection rows with a non-empty artwork URL (not a live image-validity check); attributes include total, covered, missing counts, up to 25 missing titles, `artwork_missing_by_reason` counts, and up to 10 sample titles per reason, plus `artwork_lookup_status_counts` and up to 10 missing-item samples per provider lookup status. Lookup statuses distinguish missing API keys, unavailable or malformed platform catalogs, unmapped platforms, provider/network failures, exact-title misses, unverified front covers, and verified covers.
- **Switch Games** — rows whose platform is Switch.
- **Switch 2 Games** — rows whose platform is Switch 2.
- **Configured Platform Games** — full-game rows for the platform selected in this integration entry; use this sensor for PlayStation, Xbox, retro consoles, or `All Platforms`.
- **Physical Games** — rows marked physical.
- **Digital Games** — rows marked digital.

### Physical inventory and lending

- **Games In Possession**
- **Games Lent Out**
- **Games Overdue**
- **Total Physical Copies**
- **Active Game Loans**
- **Game Lending History**
- **Inventory Needs Review**
- **Unmatched Physical Games**

Entity IDs are generated by Home Assistant from the configured device and entity names. Use the IDs shown in your instance.

Sensor attributes expose bounded lists (up to 500 records) and include a truncation flag. Collection `items` attributes include `image`, `description`, `item_type` (`game` or `dlc`), and `parent_game` when available. DLC using its parent's verified cover also includes `artwork_inherited: true`. Large list attributes (`items`, `copies`, and `recent_events`) are excluded from Recorder history to avoid its 16 KiB attribute limit; they remain available in live entity state for the Lovelace card. Count values and small status attributes continue to be recorded. The lending-history sensor exposes the 20 most recent events; the complete history remains stored locally.

## Services

All services accept an optional `config_entry_id` when multiple collections are configured.

- `dekudeals.refresh_collection` — fetch the latest public export and reconcile inventory.
- `dekudeals.refresh_artwork` — retry cached artwork lookups without clearing collection data or physical inventory.
- `dekudeals.register_copy` — register a physical copy not represented by the export (`game`, optional `platform`, `notes`).
- `dekudeals.lend_game` — lend a copy (`copy_id`, `borrower`, optional `due_date` in YYYY-MM-DD format and `notes`).
- `dekudeals.return_game` — return a loan (`copy_id`).
- `dekudeals.update_inventory` — update copy notes (`copy_id`, `notes`).
- `dekudeals.resolve_inventory_match` — resolve a review item (`copy_id`, `resolution`: `present`, `not_present`, or `manual`).

Only physical copies can be lent. Digital collection entries are not added to physical inventory.

## Data and privacy

The integration requests the public collection export and eligible public item pages over HTTPS. It does not ask for or store your DekuDeals password. Game metadata is cached in Home Assistant local integration storage. Physical-copy details, borrower names, notes, and lending history are stored locally in Home Assistant's integration storage and are not sent to DekuDeals.

## Troubleshooting

- If setup cannot reach the export, confirm the collection is public and the URL is correct.
- You can paste a saved JSON export as a fallback during setup, or add one later through **Configure**.
- Use `dekudeals.refresh_collection` to request an immediate live refresh.
- Check the Home Assistant logs for messages from the `dekudeals` integration.

## Development

The repository runs unit tests, Python compilation, Home Assistant hassfest validation, and HACS validation in GitHub Actions.
