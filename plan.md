# Crump Modernization Plan

Tracking checklist for bringing Crump back to life. Last touched substantively in 2017;
both scripts are Python 2-only and fail at compile time under Python 3.

**How to use this file:** check boxes as work lands. Each phase has a short
rationale so the *why* survives context loss. Phases are ordered by dependency —
Phase 0 changes the shape of everything downstream, so it goes first.

---

## Phase 0 — Reckon with the new data source (do this first)

The old fixed-width `cisbemon.txt` pipeline is obsolete. The SCC replaced it with a
ZIP of CSVs. **This invalidates a large part of the codebase**, so settling it before
porting avoids porting code we're about to delete.

### Confirmed facts (verified 2026-08-25)

- [x] New source URL: `https://cis.scc.virginia.gov/DataSales/DownloadBEDataSalesFile`
- [x] Download requires a cookie gate, **no login/account**:
  1. `GET https://cis.scc.virginia.gov/Cookie/CookieConsent` (establish session)
  2. `POST https://cis.scc.virginia.gov/Cookie/StoreCookieConsent` with
     `Content-Length: 0` → sets a `cookiesAccepted` cookie
  3. `GET .../DataSales/DownloadBEDataSalesFile` → 177 MB `application/zip`
  - A `POST` without an explicit `Content-Length: 0` returns **HTTP 411**.
- [x] Old S3 mirrors are **dead — HTTP 403**: `s3.amazonaws.com/virginia-business/current.zip`
      and `.../addresses.db`, the URLs hardcoded in the 2017 code. **There is no
      `virginia-business` bucket** (confirmed 2026-08-25) — the real bucket is
      **`data.vabusinesses.org`**, which is what the old `converter.sh` on the
      `csv-parser` branch uploaded to. The 403s were a dead bucket name, not a
      permissions problem. `addresses.db` has since been **recovered from a local
      copy** (see Phase 4), and `current.zip` is superseded by the new CIS
      download.
- [x] Archive contains **11 CSVs, ~1 GB uncompressed**, refreshed regularly
      (files dated 2 days before inspection):

  | File | Size | Rows (approx) |
  |---|---|---|
  | `Corp.csv` | 209 MB | 513,550 |
  | `LLC.csv` | 647 MB | 1,556,674 |
  | `Officer.csv` | 70 MB | 1,189,921 |
  | `NameHistory.csv` | 36 MB | — |
  | `Amendment.csv` | 18 MB | — |
  | `ReservedName.csv` | 14 MB | — |
  | `LP.csv`, `Merger.csv`, `GP.csv`, `BT.csv`, `PSA.csv` | 0.05–5 MB | — |

  Note `GP.csv`, `BT.csv`, `PSA.csv` are **new entity types** with no old equivalent.
  `Corp`/`LLC`/`LP`/`GP`/`BT`/`PSA` share one common column set (with small
  additions: `Stock1` on Corp/BT; series columns on LLC).

### Decisions — SETTLED 2026-08-25

**Crump's new role: CSV normalizer / geocoder / data-enhancer.** It no longer parses
a fixed-width file; it consumes the upstream CSVs and adds value on top — cleaning,
renaming, geocoding, and emitting CSV/JSON.

- [x] **Rewrite boundary: option (a).** Rewrite `crump` as a CSV
      normalizer/geocoder/enhancer, **keeping the YAML maps**. Preserves the
      `snake_case` output names downstream consumers depend on.
- [x] **Delete our hand-maintained code tables; defer to upstream.**
      `table_maps/1_tables.yaml` and `table_types.csv` go away, along with the whole
      `table_id` lookup path — the SCC now ships those values pre-expanded.
- [x] **Weekly refresh cadence confirmed** as still correct.

#### What that means concretely for `table_maps/*.yaml`

The maps are being **repurposed, not preserved wholesale**. Per-key disposition —
counts are across all 9 map files:

| Key | Count | Disposition |
|---|---|---|
| `start` | 149 | **DELETE** — fixed-width offsets, no meaning for CSV |
| `length` | 148 | **DELETE** — same |
| `table_id` | 32 | **DELETE** — upstream pre-expands these |
| `alt_name` | 151 | **KEEP** — the `snake_case` renaming layer; the main asset |
| `description` | 151 | **KEEP** — no upstream data dictionary exists (verified) |
| `type` | 189 | **KEEP** — drives type coercion |
| `search` | 63 | **KEEP** — Elasticsearch hints (Phase 6) |
| `group` | 38 | **KEEP** — marks address field clusters for the geocoder |
| `transform` | 5 | **KEEP** — still needed, see below |

- [x] **Rekey each map entry from `start`/`length` to the upstream CSV column name.**
      DONE. Every entry is now `source:` (upstream header) + `alt_name:` (emitted
      name). Dropped the internal-only `name:` key. Verified: **0 occurrences of
      `start`/`length`/`table_id` remain**.
- [x] **Rename the map files to match upstream.** DONE — map filenames now match the
      upstream CSV stems (`corp.yaml` ↔ `Corp.csv`), so lookup is mechanical.
      Deleted `1_tables.yaml` and `table_types.csv`.
- [x] **Add maps for the three new entity types** — DONE: `gp.yaml`, `bt.yaml`,
      `psa.yaml`. Correction to an earlier note: **`BT` does *not* have `Stock1`** —
      it has the plain 28-column core. Only `Corp` has `Stock1` (29 cols); `LLC` has
      the 3 series columns (31 cols); `LP`/`GP`/`BT`/`PSA` are 28 cols exactly.
- [x] **`group: address` is now load-bearing** — DONE in the maps. Two distinct
      groups per entity file: `group: address` (principal office) and
      `group: ra_address` (registered agent). `reservedname.yaml` also has one
      `address` group for the requestor. Each group carries a `derived: geocode`
      entry naming its output field (`coordinates` / `agent_coordinates`).
      - [ ] Still to do in code: drive geocoding off `group` and retire the hardcoded
            `file_number == '2' or '3' or '9'` check at [crump:366](crump#L366) and the
            manual `line['coordinates']` naming at [crump:391](crump#L391) (the
            existing `FIX THE BELOW` comment asks for exactly this).

#### `transform:` blocks stay — upstream does NOT expand these

Verified: while `Status`/`StatusReason`/`IndustryCode`/`RA-Status` arrive pre-expanded,
the fields with `transform:` blocks are **still raw codes** upstream:

- `NameHistory.NameStatus` → `70` (110,522) / `50` (89,478) — map has `50: fictitious
  name`, `70: old name`
- `ReservedName.Status` → `61` (91,138) / `60` (971) — map has `60: registered`,
  `61: reserved`
- `Merger.MergerType` → `N` (40,334) / `S` (31,123) — map has `N: non-survivor`,
  `S: survivor`

- [x] Keep the `transform:` expansions — DONE, carried into `namehistory.yaml`,
      `reservedname.yaml`, `merger.yaml`, plus a new one on `StockInd` (`S`→stock,
      `N`→nonstock). YAML-quoted the numeric keys (`'50'`, `'70'`, `'60'`, `'61'`) so
      they load as strings and actually match the CSV values — unquoted they'd parse
      as ints and silently never match.
      - [ ] Still to do in code: **apply** them. The old hot loop only honored
            `table_id`, so these expansions likely never ran.
- [x] **Handle undocumented codes** — documented in `reservedname.yaml`.
      `ReservedName.Type` ships `X` (32,565 rows) and empty (56,142), neither in the
      old `C`/`L` map.
      - [ ] Still to do in code: pass unknown codes through unchanged, log once per run.

#### Map schema (as built — this is now the contract)

Each map is a list of field entries. `table_maps/<stem>.yaml` ↔ `<Stem>.csv`.

| Key | Meaning |
|---|---|
| `source` | Upstream CSV header. **Absent = derived field** (not read from CSV). |
| `alt_name` | Name Crump emits. Required on every entry. Unique within a file. |
| `description` | Human documentation. Required — no upstream data dictionary exists. |
| `type` | `A` text, `N` numeric, `D` date, `Z` ZIP, `B` boolean. Drives coercion. |
| `group` | Marks field clusters: `address`, `ra_address`, `officer_name`, `amendment_type`. |
| `transform` | Code→label expansion for the fields upstream leaves raw. |
| `derived` | How to compute a field with no `source`: `geocode` or `foreign_from_state`. |
| `search` | Elasticsearch hints (`type`, `match`) — consumed in Phase 6. |

Totals: **11 maps, 208 mapped upstream columns, 19 derived fields.**
Validated bidirectionally — every upstream column is mapped exactly once, and no map
references a column that doesn't exist. Worth keeping as a test (see Phase 5).

Three `type` values are new and encode the Phase 0 quirks: `D` (already-ISO dates, so
*don't* reformat), `Z` (ZIP passthrough/validation, not reformatting), `B` (boolean).

Derived fields, by design rather than accident:
- `foreign` — `IncorpState != 'VA'`, replacing the old fixed-width `corp-foreign` flag
- `coordinates` / `agent_coordinates` — geocoder output per address group

#### Download behavior

- [x] Implement the cookie-gate download sequence behind `-d`. DONE in `crumplib/download.py`, including the `Content-Length: 0` requirement and a content-type guard that fails loudly if the gate changes.
- [ ] With a weekly cadence, cache by `Last-Modified`/`ETag` or the ZIP's internal file
      dates and skip re-downloading 177 MB when unchanged.
- [x] **Archiving the source ZIP to S3: not doing it** (decided 2026-08-25).
      The SCC endpoint only ever serves "current", so weekly history would have to
      be archived by us — as `converter.sh` on the old `csv-parser` branch used to
      do, leaving 31 dated ZIPs (2014-05-21 → 2016-09-13) plus a 2018 straggler
      still sitting in `data.vabusinesses.org`. **Those files are no longer
      relevant and will not be resumed or extended.** Crump downloads the current
      file and normalizes it; it does not mirror upstream.
      Consequence to accept knowingly: there is **no historical archive** of the
      SCC feed going forward, and no way to reconstruct a past week's data.

### New CSV quirks — legacy of the fixed-width era

These are the "some transformations may still apply" cases. All verified against
`Corp.csv`:

- [x] **Every field is space-padded to fixed width.** e.g. `INACTIVE  `,
      `VA        `. **Must `.strip()` every value.** This is the fixed-width format
      leaking through. The existing internal-whitespace squeeze at
      [crump:351](crump#L351) is still useful for *interior* runs.
- [x] **`EntityID` is prefixed with a literal TAB** — `'\t11683582  '`. An Excel
      "force text" trick. Must strip the tab as well as spaces.
- [x] **Data rows have one MORE field than the header.** Header has 29 columns,
      rows have 30 — a trailing comma creates a phantom empty column. `DictReader`
      will bucket it under `None`. Applies to *every* file in the archive.
      Must be explicitly discarded.
- [x] **Dates are already ISO `YYYY-MM-DD`** — the manual slice-and-rejoin at
      [crump:303](crump#L303) is now actively harmful and should be **deleted**.
- [x] **`9999-12-31` is the null sentinel** (not the old `9999-99-99` / `0000-00-00`).
      Nearly all `Duration` values are `9999-12-31`. Map to `None`.
      The `>= 9900` guard in `convert_date` ([crump:550](crump#L550)) still helps.
- [x] **`TotalShares` is a float string** — `5000.0`, `0.0`, or empty. The old
      `int()` cast at [crump:342](crump#L342) raises `ValueError` on all of these.
      Parse as float→int, treat empty as `None`.
- [x] **ZIP is mostly `99999-9999`, already hyphenated** — but also `99999`, empty,
      6-digit, 4-digit, and **Canadian postcodes** (`M9J9B9`). The 9-digit
      re-hyphenation logic at [crump:315](crump#L315) mostly no longer applies;
      rewrite as validation/passthrough rather than reformatting.
- [x] **Encoding is UTF-8**, not the old high-byte-mangled ASCII (verified: decodes
      clean; contains e.g. `è`). **Confirmed across all 11 files** — every one
      decodes as clean UTF-8. `character_map.yaml` and `replace_non_ascii()` are
      therefore obsolete and have been **deleted**.
- [x] **Line endings are CRLF.** Open with `newline=''` and let `csv` handle it.
- [x] **`StockInd` is `S`/`N`**, and the old `foreign` (`F`/`0`) and `domestic`
      (`M`/`L`) flags no longer appear as such — `IncorpState` now carries formation
      state directly (`VA`, `DE`, `MD`, …). Re-derive the foreign/domestic boolean
      from `IncorpState != 'VA'` and delete the old branches at
      [crump:326-338](crump#L326-L338).

---

## Phase 1 — Dependencies

- [x] Pin versions with **upper bounds** in `requirements.txt`; `>=`-only floors are
      what let the ecosystem drift out from under this project.
- [x] **Drop `csvkit` entirely; use stdlib `csv`.** DONE. [crump:228](crump#L228) calls
      `csvkit.CSVKitDictReader`, which no longer exists (csvkit 2.2.0 exposes only
      `DictReader`/`DictWriter`). We only ever used those two, and csvkit is now
      built on `agate`, dragging in `agate-dbf`, `agate-excel`, `agate-sql`.
      Removes 4+ transitive deps and this whole breakage class.
- [x] **Fix `yaml.load()`** → `yaml.safe_load()`. DONE in `crumplib/maps.py`.
- [x] **Remove the vestigial `zipp>=3.19.1` Snyk pin** — transitive artifact,
      nothing imports it.

---

## Phase 2 — Python 3 port — COMPLETE

Rewritten rather than line-by-line ported, since Phase 0 retired the fixed-width
parser. Logic now lives in a `crumplib/` package; `crump` and `geocode` are thin
CLIs over it, which is what makes any of it testable.

New layout:

| File | Role |
|---|---|
| `crumplib/normalize.py` | Field-level cleaning: padding, dates, ZIPs, numbers, states |
| `crumplib/geocache.py` | Address hashing + `addresses.db` lookups |
| `crumplib/maps.py` | YAML map loading; generic address-group discovery |
| `crumplib/records.py` | Row → normalized record, incl. transforms and geocoding |
| `crumplib/output.py` | CSV, JSON-array, and JSON-lines writers |
| `crumplib/download.py` | Cookie-gated SCC download and extraction |
| `crump` | CLI: normalize the CSVs |
| `geocode` | CLI: geocode addresses not yet cached |

- [x] **Address-hash byte encoding frozen and verified.** The recipe is
      `md5((s1 + "," + s2 + "," + city + "," + state + "," + zip).encode("utf-8"))`
      with uppercase / USPS-abbreviation / ZIP5 normalization. Pinned by
      `tests/test_geocache.py`, which asserts the known production hash
      `6628 ELECTRONIC DR,,SPRINGFIELD,VA,22151` →
      `e85df274dcf6ba70be4a9ecd32c0596d`, **and** that the CSV-feed form of the
      same address (mixed case, "Virginia", ZIP+4) hashes identically.
      Measured live: **35.9% of addresses geocode from cache**.
- [x] `print` statements → functions.
- [x] `except X, e` → `except X as e`; `sqlite3.error` → `sqlite3.Error`.
- [x] `urllib2`/`urllib.urlencode` → `requests`, which also handles the cookie
      gate the new download needs.
- [x] Binary downloads open `"wb"`; the download streams in 1 MB chunks rather
      than buffering 177 MB in memory.
- [x] CSVs open in text mode with `newline=""` and `encoding="utf-8"`.
- [x] **Replaced the hand-rolled JSON assembly.** No more
      `seek(-2, os.SEEK_END)` + `truncate()` (illegal on a text-mode file in
      Python 3). `JsonArrayWriter` writes the separator *before* each record;
      default output is now JSON Lines, which streams and appends cleanly.
      Verified the empty-input case still emits valid `[]`.
- [x] Both scripts compile and run: `python3 -m py_compile crump geocode` passes,
      and a full 11-file run produces 163,121 records with stable column widths.

## Phase 3 — Logic bugs

These are genuine defects independent of the port — each verified by execution.
Items 3, 4, 6 and the `zip`/date cases may be **deleted rather than fixed** if
Phase 0 removes those transformations.

- [x] **1. `checksum()` crashes on carry** — **DELETED.** It was dead code (nothing
      called it), it was broken two ways (`int` subscripting, and the digit-sum
      needed `tmp - 9`), and the CSV feed gives us `EntityID` directly, so there is
      nothing to validate a check digit against. Removed rather than fixed.
- [x] **2. `last_day()` is accidentally correct** — FIXED. Now
      `normalize._days_in_month()` using `calendar.monthrange(year, month)[1]`,
      covered by parametrized leap-year tests.
- [x] **3. ZIP `'000000000'` mangled to `'-'`** — FIXED in `normalize.parse_zip()`,
      which returns early for all-zero values. **Also found a related bug while
      testing**: an already-hyphenated `23219-0000` kept its meaningless `-0000`
      (the old code only handled the unseparated form). Both cases now trim.
- [x] **4. Date slicing corrupts malformed input** — FIXED by deletion. The feed
      already ships ISO dates, so `normalize.parse_date()` validates against a
      regex instead of reformatting. No bare `except` remains; out-of-range
      components are coerced deliberately, not swallowed.
- [x] **5. `if 'street_1' in 'record'`** — FIXED. `geocode.street_for_lookup()`
      filters a list of usable street lines instead of testing dict membership.
- [x] **6. `int(line[name]) + 0`** — FIXED. `normalize.parse_number()` parses via
      `float()` (the feed ships `'5000.0'`), returns `None` for blank and
      non-numeric, and keeps the all-9s null convention.
- [x] **7. `del record['street_1']` then read back** — FIXED. `is_postal_box()`
      classifies PO-box and care-of lines and `street_for_lookup()` filters them,
      so no key is ever deleted and re-read.
- [x] **8. Wrong `source_api` provenance** — FIXED. Each geocoder reports its own
      source (`VGIN` / `Census`). Verified live: new out-of-state rows are labeled
      `Census`, the Virginia row `VGIN`.
      - [ ] The 22,731 pre-existing `Census`-sourced rows in the shipped cache were
            already labeled correctly; no backfill needed. But note any rows the
            *old* code wrote out-of-state carry the wrong `VITA` label.
- [x] **9. Linear scan in the hot loop** — [crump:355](crump#L355). ~~Scans
      `lookup_table` per field per line across millions of lines.~~
      **Resolved by deletion**: Phase 0 retires the `table_id` lookup entirely, since
      upstream pre-expands these values. No dict-index needed.
- [x] **10. `lookup_table` ordering dependency** — [crump:227](crump#L227).
      **Resolved by deletion** — same as item 9. The new CSVs are separate files with
      no cross-file ordering dependency, so this class of bug is gone.
- [x] Note: the `corp-foreign`/`corp-id` overlap at `start: 2` in
      `2_corporate.yaml` was **intentional**, not a bug — the ID's first character
      doubled as the foreign flag. **Moot**: the `start` offsets are being deleted, and
      `foreign` is now derived from `IncorpState != 'VA'`.

---

## Phase 4 — Geocoding

- [x] **Update the VITA endpoint.** DONE. `gismaps.vita.virginia.gov` **no longer
      resolves** (`NXDOMAIN`) — [geocode:210](geocode#L210). Virginia moved GIS to
      VDEM. Working replacement:
      `https://vginmaps.vdem.virginia.gov/arcgis/rest/services/Geocoding/VGIN_Composite_Locator/GeocodeServer`
- [x] **Rename the query parameters** DONE. — the service contract changed. Verified via
      service metadata and a live query returning **score 100**:
      | Old | New |
      |---|---|
      | `Street` | `Address` |
      | `City` | `City` (unchanged) |
      | `State` | `Region` |
      | `ZIP` | `Postal` |
      A single-line `SingleLine` field is also available.
- [x] **Census geocoder moved to HTTPS.** DONE.
- [x] **`addresses.db` recovered** (copied in locally, 2026-08-25). No longer need
      the dead S3 copy. Verified contents:
      - 85 MB, `PRAGMA integrity_check` → **ok**
      - **564,848 rows**, all with non-null, non-zero coordinates
      - Sources: 542,117 VITA + 22,731 Census
      - Geocoded **2014-10-19 → 2015-03-01**
      - 521,836 (92%) fall inside the Virginia bounding box; 43,012 out-of-state
- [x] **Confirmed the hash recipe** from [crump:372](crump#L372) is
      `md5(street_1 + "," + street_2 + "," + city + "," + state + "," + zip)`,
      by exactly reproducing a known `address_hash` from the DB.
- [x] **Apply address normalization to reuse the cache — DONE, and measured at 35.9% on a live run.**
      A naive lookup against the new CSVs scores **0% hits**. Two format changes in
      the new feed break the exact-match MD5:
      1. **Case**: new CSV is mixed-case (`Via Lago Dr`), cache was built from
         upper-case input (`ELECTRONIC DR`)
      2. **State**: new CSV spells states out (`Virginia`), cache used the USPS
         abbreviation (`VA`)
      3. **ZIP**: cache keys used **ZIP5**; new CSV mostly ships `99999-9999`
      Normalizing to `upper()` + USPS abbreviation + ZIP5 lifts the hit rate from
      **0% → 38%** on a Corp.csv sample. Spot-checked 6 recovered rows: street,
      city, and ZIP all agree and coordinates land correctly. Using ZIP5 beats the
      full hyphenated ZIP by ~8x (38% vs 4.7%).
      - [x] Built the full 50-state + DC + territories map
            (`normalize.STATE_ABBREVIATIONS`)
      - [ ] Still open: whether to **rehash the cache** to a normalized key rather
            than normalizing on every lookup. Current approach normalizes at lookup
            time, which works and needs no migration; rehashing would be faster in
            steady state. Not urgent.
      - [x] Preserved raw input as the key — matching on the geocoder-*normalized*
            `address_cleaned` scored **worse** (33%), so raw input stays the key
- [x] **Size of the remaining job** — measured across `Corp.csv` + `LLC.csv` + `LP.csv`,
      counting both principal-office and registered-agent addresses:
      | Metric | Count |
      |---|---|
      | Total address instances | 4,076,195 |
      | — served from cache | 995,387 (**24.4%**) |
      | Unique addresses | 1,668,571 |
      | — unique served from cache | 304,393 (18.2%) |
      | **Unique still needing geocode** | **1,364,178** |
      So the cache is worth roughly **300k geocodes / ~1M lookups** — real savings,
      but it covers well under half the corpus. At the current 1 req/sec throttle
      ([geocode:317](geocode#L317)), the remaining 1.36M unique addresses is
      **~16 days of continuous running**.
- [x] **Census batch endpoint implemented and validated against the live service**
      (`crumplib/batch.py`, `geocode -b`). Tested on real uncached SCC addresses.

      **Viability: yes, decisively.** Measured:
      | Batch | Wall clock | Match rate |
      |---|---|---|
      | 100 addresses | 0.6 s | 75% (PO boxes included) |
      | 1,000 addresses | 4.1 s | 82% (PO boxes pre-filtered) |

      Serially at 1 req/sec, that 1,000-address batch would take ~17 minutes.
      Extrapolating to the 1.36M backlog: **roughly 1.5–2 hours of API time
      instead of ~16 days.**

      Service contract (from the Census docs, confirmed live):
      - `POST https://geocoding.geo.census.gov/geocoder/locations/addressbatch`
      - multipart `addressFile` upload plus `benchmark=Public_AR_Current`
      - input CSV is **headerless**, exactly `Unique ID, Street address, City, State, ZIP`
      - **10,000 records per request** is the documented ceiling
      - the unique ID is echoed back, so we submit the **address hash** and results
        drop straight into the cache with no re-derivation
      - US, Puerto Rico, and Island Areas only — so the feed's Canadian addresses
        can never match and shouldn't be submitted

      - [x] **Pre-filter PO boxes.** 17 of 25 no-matches in the first test were PO
            boxes, which the service never matches. Reusing `street_for_lookup()`
            lifted the match rate from 75% → 82% *and* stopped wasting batch slots.
      - [x] **Guard against wrong-location matches — the real risk.** The service
            returns `Non_Exact` matches that name a **different street**:
            `1 W Nationwide Blvd` → `1 E NATIONWIDE BLVD`,
            `204 W Washington St` → `204 E WASHINGTON ST`. Measured at
            **10 of 821 matches (1.2%)**. Since these get cached and served as a
            business's location, `batch.directional_conflict()` rejects them.
            It distinguishes genuine contradictions from benign normalization
            (`EAST QUEENS DRIVE` → `E QUEENS DR` is fine; so is a directional
            *added* to disambiguate). Override with
            `--allow-directional-conflicts`.
      - [x] **Handle `Tie`** — an undocumented third status for ambiguous
            addresses. Recorded as a failure, distinct from `No_Match`.
      - [x] **Handle the 3-column short row.** Unmatched rows come back with only
            three fields; indexing past that raises `IndexError`.
      - [x] **Deduplicate before submitting.** Addresses repeat heavily across
            entities (585 duplicates in an 8,000-record sample), so batching
            deduplicates by hash first.
- [x] **Both geocoders coexist, as intended.** `geocode -b` sends non-Virginia
      addresses to the Census batch API and keeps Virginia addresses on the VGIN
      locator one at a time, since the state service is more accurate for Virginia.
      `--batch-all` overrides. Verified in one run: 560 batched (80% matched) plus
      2,292 Virginia addresses via VGIN, with correct per-source provenance.
      - [ ] **Not yet done: the actual 1.36M backfill run.** The machinery is
            tested; this is just the compute. Worth doing on the weekly job or a
            one-off, and it wants the VGIN serial path to run overnight.
- [ ] **Expect cache decay.** The cached geocodes are 11+ years old (2014–15). New
      construction and re-addressing since then won't be represented, which is part
      of why the hit rate is 18% on unique addresses. Consider a `date`-based
      re-geocode policy for the oldest entries.
- [x] **Schema flaw noted and fixed going forward**: new tables declare
      `latitude`/`longitude` as `REAL`. The existing `addresses.db` keeps its
      `INTEGER` declaration — SQLite's dynamic typing means the stored floats are
      fine, so this needs no migration.
- [x] **Record geocoding failures** in the DB. DONE — new `failures` table storing
      the hash, timestamp, and reason. `--retry-failures` re-attempts them. This
      resolves the old `###` comment asking for exactly this.

---

## Phase 5 — Tooling, packaging, tests

- [x] **Deleted `.travis.yml`; added GitHub Actions.** `.github/workflows/test.yml`
      runs pytest + ruff (lint and format) on 3.11/3.12/3.13 and smoke-tests both
      CLIs.
- [x] **Added `pyproject.toml`** with metadata, pinned deps, a `dev` extra, and
      pytest/ruff config. Note: the CLIs stay as executable scripts rather than
      console entry points, so `./crump` keeps working as before.
- [x] **Moved `argparse` into `parse_args(argv)`**, called from `main(argv)`. No
      module-level globals remain; the `character_map` global is gone entirely.
- [x] **Added a test suite** — **84 tests, all passing** (`pytest`):
      | File | Covers |
      |---|---|
      | `tests/test_normalize.py` | padding/tab stripping, dates, ZIPs, numbers, booleans, state abbreviation |
      | `tests/test_geocache.py` | the address-hash contract, cache hits/misses, missing-file tolerance |
      | `tests/test_maps.py` | map/CSV coverage, unique output names, no legacy keys, string transform keys |
      | `tests/test_records.py` | row → record, derived fields, transforms, unknown-code capture |
      Every Phase 0 quirk has a named test. The suite already earned its keep: it
      caught the `23219-0000` ZIP bug that manual testing missed.
- [x] **Added ruff** config and wired both `check` and `format --check` into CI.
      `ruff check .` passes clean (fixed 12 findings: percent-formatting, a missing
      `raise ... from`, and an unused loop variable).
- [x] **Rewrote the README** for the new CLI, the eleven upstream CSVs, the field
      maps, and the geocoding workflow. Dropped the phantom `-a/--atomize` docs and
      the dead S3 links.
- [ ] **Replace the Snyk badge** if that integration is no longer active.

---

## Phase 6 — Elasticsearch (only if there's still an ES target)

The generated mappings won't load into any supported Elasticsearch version.

- [ ] `"type": "string"` → `text`/`keyword` — [crump:170](crump#L170),
      [crump:176](crump#L176). Removed in ES 5.0 (2016).
- [ ] `"index": "not_analyzed"` → `keyword` type — [crump:191](crump#L191).
      Also removed in ES 5.0.
- [ ] Drop `_type` from bulk metadata — [crump:408](crump#L408). Removed in ES 8.
- [ ] GeoJSON `'type': 'point'` → `'Point'` (capitalized) —
      [crump:419](crump#L419).
- [ ] Reconsider the 100k-line `chunk()` splitting ([crump:459](crump#L459)) —
      modern bulk helpers stream and batch by payload size, not line count.

---

## Open questions

- [x] **The S3 bucket is `data.vabusinesses.org`** (corrected 2026-08-25).
      There is no `virginia-business` bucket — that name came from the dead URLs
      hardcoded in the 2017 code, and my earlier AccessDenied diagnosis was
      therefore **wrong**: those calls failed because the bucket does not exist,
      not because of a missing IAM grant.
      - [ ] **Re-test access against the correct bucket** before the first real
            publish. The earlier permissions finding should be treated as
            unverified until then.
- [ ] Is an 11-year-old geocode good enough to keep, or should cached entries past
      some age be re-verified? (Affects the 18% hit rate.)
- [x] **Elasticsearch: on hold.** Phase 6 stays unchecked and unstarted by decision, not oversight.
- [x] **`GP`, `BT`, and `PSA` are first-class outputs.** Already satisfied by the
      Phase 0 map work: each has a full map (31 output fields), both address groups,
      CSV/JSON output, and a per-entity JSON file. Verified in a full run:
      GP 7,535 · BT 1,942 · PSA 132 entities.
- [x] **Atomize kept and rebuilt** — it backs a static API in S3. See Phase 7.

---

## Phase 7 — Atomize and publish (static S3 API) — COMPLETE

Per-entity JSON files, served straight from S3 as a static API. Rebuilt rather
than restored: the 2015 implementation (removed in `c7f6cd7`) wrote a flat
`output/<file_number>/<corp_id>.json`, which does not survive 2 million files.

- [x] **`crumplib/atomize.py`** — writes one JSON file per entity, sharded.
- [x] **Single flat namespace is safe.** Verified across the full feed: the six
      entity types share **zero** overlapping IDs (2,049,921 IDs, 2,049,921
      unique). So consumers can look up an ID without knowing its entity type.
      Each document still carries `entity_type` so it is self-describing.
- [x] **Shard depth 4, chosen from measurement, not taste.** Entity IDs cluster
      hard by issue era, so a shallow prefix does not spread them:
      | Depth | Shards | Largest shard |
      |---|---|---|
      | 2 | 31 | 869,397 files (40% of all output) |
      | 3 | 223 | 89,029 files |
      | **4** | **2,136** | **9,110 files** |
      Depth 2 was the first implementation; the full-scale run exposed the `11`
      shard holding 849,148 files, which defeats the point of sharding. The
      tests now assert against `SHARD_DEPTH` rather than hardcoded paths.
- [x] **Related records nest into the entity document** — `officers`,
      `name_history`, `amendments`, `mergers`, normalized through the same maps.
      Indexed in one pass and held in memory; the related files are small next to
      the entity files. Measured fan-out: max 154 officers, 722 name-history rows
      for a single entity.
      `ReservedName` is deliberately excluded: it is keyed by reservation number,
      not entity ID, so it has no entity to hang off.
- [x] **Path safety.** Entity IDs become filesystem paths, so `safe_id()`
      validates against an allowlist and rejects traversal (`../`, separators,
      empties). A bad ID is counted and skipped, never fatal — one malformed row
      must not abort a 2-million-record run.
- [x] **`crumplib/publish.py`** — `aws s3 sync` wrapper. Shells out on purpose:
      sync already does parallelism, retries, and skip-unchanged for millions of
      small objects. Sets `application/json` and a cache header; `--exclude *
      --include *.json` so stray local files can never reach a public bucket.
      `--delete` is **off by default** (a partial run plus `--delete` would erase
      most of the API).
- [x] **Full-scale run verified**: 4,141,128 records and **2,093,343 per-entity
      JSON files** (7.8 GB) in **~4 minutes**. 2,136 shards, largest 8,929 files.
- [x] **34 new tests** (`tests/test_atomize.py`, `tests/test_publish.py`);
      **122 passing** overall.

### Remaining before the first real publish

- [ ] **Grant the IAM user access to the bucket** — see the open question above.
      Needs `s3:ListBucket` plus `s3:PutObject` on the `entity/*` prefix.
- [x] **Public URL shape: bare JSON filenames, sharded paths, documented.**
      Decided 2026-08-25 — keep `entity/<4-char-shard>/<id>.json` as-is. No
      CloudFront rewrite for now; the sharding rule is documented in the README.
- [ ] **Decide on `index.json`.** `Atomizer.write_index()` exists but is not
      wired into the CLI — a 2-million-entry manifest is ~25 MB, which is fine to
      generate but questionable to serve. Probably wants to be per-shard instead.
- [ ] **Set a CORS policy** on the bucket, or browser clients cannot read it.
      *Deferred by decision (2026-08-25) — not blocking, but the API is
      unusable from a browser until it is set. One-time bucket config, no code
      change:* `AllowedMethods: [GET, HEAD]`, `AllowedOrigins: ["*"]`,
      `AllowedHeaders: ["*"]`.
- [ ] **Consider `--delete` on the weekly job** so terminated entities disappear,
      but only after a full-run guard exists — never on a `--limit` run.

---

## Phase 8 — SQLite database (`./db_load`) — COMPLETE

A queryable SQLite build of the normalized records, for analysis and for
publishing to S3. **Deliberately not part of the build or CI**: the database is a
derived artifact, rebuilt when new weekly data lands.

- [x] **`crumplib/database.py` + `./db_load` CLI.**
- [x] **Schema derived from the YAML field maps**, not hand-written — adding a
      field to a map is the only change needed. Type mapping:
      `A`/`D`/`Z` → TEXT (dates as ISO 8601, since SQLite has no date type and
      ISO strings sort correctly), `N` → INTEGER, `B` → INTEGER 0/1.
- [x] **Coordinates split into `<field>_latitude` / `<field>_longitude` REAL
      columns** rather than a JSON array, so bounding-box queries work and can
      use a composite index. Verified: `EXPLAIN QUERY PLAN` shows
      `SEARCH corp USING INDEX corp_coordinates`.
- [x] **Reserved-word columns quoted.** `foreign` is SQL-reserved; unquoted it is
      a syntax error. Covered by a test.
- [x] **No PRIMARY KEY on entity tables — and this matters.** The first version
      made `id` a primary key with `INSERT OR REPLACE`, which loaded 17,950 rows
      from a 20,000-row corp CSV. Investigated rather than accepted: the SCC
      ships **multiple rows per entity** where registered-agent or merger history
      differs (1,723 of 17,950 corp entities; the varying fields are
      `agent_date` and `merged`). The primary key was silently discarding real
      data. Now `id` is indexed but not unique, `INSERT` is plain, and
      repeatability comes from dropping tables first. Row counts now match the
      CSVs exactly.
- [x] **Indexes built after loading, not during** — markedly faster. Then
      `ANALYZE` for the query planner and `VACUUM` to compact before upload.
- [x] **Full-scale verified**: **4,141,128 rows in 38 seconds → 1.2 GB**, row
      counts matching every source CSV exactly, `PRAGMA integrity_check` ok,
      indexed queries returning in ~5 ms.
- [x] **Fixed a bug found only at scale**: the loader inherited the stdlib
      131,072-byte CSV field limit and died partway through `Officer.csv`.
      `csv.field_size_limit` is now raised in the module.
- [x] **S3 upload is a separate, opt-in step** (`--upload bucket`,
      `--upload-dry-run`). Uses `aws s3 cp` for the single large object, rather
      than the `sync` used for the millions of atomized files. A failed upload
      warns and leaves the database on disk — it never means rebuilding.
- [x] **`*.db` gitignored** (plus `-wal`/`-shm`). Previously only
      `addresses.db` was, so `crump.db` would have been committed.
- [x] **CI does not build or upload the database** — it only lints, tests, and
      checks `--help` on all three CLIs.
- [x] **34 new tests**; **183 passing** overall.

### Notes for consumers

- Entity IDs are **not unique within a table** (see above). `GROUP BY id` or
  `DISTINCT` for one row per entity.
- `--append` adds to existing tables instead of replacing them; the default
  replaces, so a re-run is repeatable rather than accumulating duplicates.

---

## Phase 9 — Jurisdiction / FIPS assignment — COMPLETE

Assign every Virginia business to the county or independent city it physically
sits in, by point-in-polygon against Census boundaries.

**Scope (set 2026-08-25):** principal office address only — not registered
agents. Annexations explicitly out of scope; Virginia boundaries are stable
enough that a pinned 2023 vintage is fine.

### Why the address cannot answer this

Measured against real geocoded data, not assumed:

| Mailing city | Actually falls in |
|---|---|
| Charlottesville | Albemarle County 161 · Charlottesville city 139 |
| Lexington | Rockbridge County 166 · Lexington city 134 |
| Richmond | Richmond city 158 · Chesterfield 88 · Henrico 54 |

A "Charlottesville" address is in Charlottesville city only **46%** of the time.
Across a full run, **42% of businesses have a mailing city that differs from
their jurisdiction** — many name places that are not jurisdictions at all
(Midlothian → Chesterfield County; Mechanicsville → Hanover County).
And Richmond city (51760) vs Richmond County (51159) makes the name genuinely
ambiguous.

- [x] **`crumplib/jurisdiction.py`** — bbox-prefiltered ray-casting
      point-in-polygon, pure stdlib. A geospatial stack (GEOS/shapely/fiona)
      would dwarf Crump's entire dependency footprint for one lookup.
      Measured ~2,500 lookups/sec; adds ~90 s to a full run.
- [x] **Boundary data shipped in `boundaries/`** — Census TIGERweb State_County
      layer, 2023 vintage, Virginia only. Trimmed to 5-decimal precision (~1 m,
      far finer than county lines need): 21.5 MB → **2.59 MB gzipped**, small
      enough to commit so runs are offline and reproducible.
- [x] **133 jurisdictions: 95 counties + 38 independent cities**, verified
      against the Census national county file.
- [x] **Three derived fields** on the six entity maps: `fips`, `jurisdiction`,
      `jurisdiction_type`. Map-driven, so they flow automatically into CSV,
      JSON, per-entity files, and SQLite.
- [x] **`fips` and `jurisdiction` indexed in SQLite.** "Every business in
      Fairfax County" returns in ~4 ms against 4.1 M rows.
- [x] **`-j` implies `-g`** — jurisdiction is derived from coordinates.
- [x] **30 new tests**; **212 passing** overall. An existing map test caught the
      new `derived: jurisdiction` type before it shipped, which is the schema
      guard working as intended.

### Full-scale results

| Metric | Count |
|---|---|
| Entity rows | 2,093,343 |
| VA principal address | 1,820,556 (87.0%) |
| Geocoded | 663,804 (31.7%) |
| **FIPS assigned** | **527,721 (25.2%)** |
| Of geocoded rows | 79.5% |

All **133 of 133** jurisdictions appear. Distribution matches Virginia's
economic geography: Fairfax County 91,566 · Virginia Beach 45,785 · Henrico
41,705; rarest are Highland 121 and Craig 99.

The 20.5% of geocoded rows without a FIPS were checked, not assumed: they are
out-of-state businesses (Maryland, California, Texas), which correctly have no
Virginia jurisdiction.

### The ceiling

- [ ] **Coverage is limited by geocoding, not by this feature.** 87% of entities
      have Virginia addresses but only 31.7% have coordinates, so only 25.2% can
      be placed. **Completing the geocode backfill is what raises FIPS coverage**
      — the two are the same project. Every point geocoded from here on gets a
      jurisdiction for free on the next run.
- [ ] **Consider `returntype=geographies` on the Census batch endpoint.** It
      returns state and county FIPS as extra columns during geocoding, at no
      extra request cost (verified live). Useful as a cross-check against local
      point-in-polygon — disagreement flags a bad geocode — though it cannot
      help VGIN-geocoded Virginia addresses, which is most of them.

---

## Phase 10 — Per-locality business lists — COMPLETE

One CSV per Virginia county and independent city, for municipal business-licensure
departments checking state registrations against their own license rolls.

**Decisions (2026-08-26):**
- [x] **All statuses included**, with a `status` column — a department filters for
      itself. 58% of placed businesses are INACTIVE; an entity terminated last
      year may still owe a licence for the year it operated.
- [x] **Filenames keep the type suffix** — `51059-Fairfax-County.csv` vs
      `51600-Fairfax-city.csv`. Four names (Fairfax, Franklin, Richmond, Roanoke)
      belong to *both* a county and an independent city, so dropping the suffix
      would put visually identical names in a directory listing.
- [x] **Columns**: id, entity_type, name, status, status_reason, status_date,
      incorporation_date, street_1/2, city, state, zip, latitude, longitude.
      Registered agents and officers deliberately excluded — an agent is usually
      a law firm at an address unrelated to where the business operates.
- [x] **No README shipped** alongside the CSVs, by decision.

- [x] **`crumplib/localities.py` + `crump -L`.** `-L` implies `-j` implies `-g`.
      Files stay open for the run (133 handles, well under any limit); records
      arrive interleaved across entity types, so append-as-you-go is the only
      single-pass option.
- [x] **Full-scale verified**: **561,751 businesses across 133 files, 100.3 MB**,
      in 5m26s. Largest Fairfax County 97,923; smallest Highland County 127.
- [x] **28 new tests**; **236 passing** overall.

### A finding worth keeping

156 rows (0.028%) have a non-Virginia `state` value despite falling inside a
Virginia boundary — e.g. an Arlington street address, ZIP 22203, Arlington
coordinates, and "Alabama" typed in the state field. **153 of the 156 carry a
Virginia ZIP.** These are SCC data-entry errors, and the geometric approach
placed them correctly *despite* the bad field, where any state-field filter
would have dropped them. Further evidence for deriving jurisdiction from
coordinates rather than address text.

### Open

- [x] **Coverage caveat: handled outside Crump** (confirmed 2026-08-26). A
      business only appears if its address could be geocoded, so a locality file
      is not a complete roster and absence is not evidence a business does not
      exist. That caveat is stated on the public download page, which lives in a
      separate project — Crump produces files, not a website. **No caveat file
      or README ships with the CSVs, and this is settled, not deferred.**
- [x] **Publishing wired up** (2026-08-26). `--publish` now uploads whatever the
      run generated rather than only atomized JSON:
      | Artifact | Prefix | Content-Type |
      |---|---|---|
      | per-entity JSON (`-a`) | `entity/` | `application/json` |
      | locality CSVs (`-L`) | `localities/` | `text/csv` |
      `sync_command()` gained an `include` parameter so each artifact uploads
      only its own file type — stray local files still cannot reach the bucket.
      **`--publish` implies both `-a` and `-L`** (changed 2026-08-26): it means
      "publish everything Crump produces". Note this transitively enables `-j`
      and `-g`, so a bare `--publish` needs `addresses.db` and costs a couple of
      extra minutes; the implication is printed at the start of the run rather
      than applied silently. If the cache is missing, locality generation yields
      nothing and Crump says so explicitly instead of reporting a successful
      zero-file sync that would leave stale files on S3.
      Prefixes are overridable via `--publish-prefix` / `--localities-prefix`.
      Verified with dry runs against `data.vabusinesses.org`.

---

## Phase 11 — Incremental publishing — COMPLETE

`aws s3 sync` was re-uploading all 2,093,343 per-entity files every week to
publish a few thousand changes. Steps 1, 3 and 4 of the proposal were
implemented; step 2 (locality CSVs) was skipped by decision.

### Diagnosis

Files average **4 KB**, so at gigabit the *bytes* would move in ~1.1 minutes —
this was never bandwidth-bound. Two separate causes:

1. **The AWS CLI default is `max_concurrent_requests = 10`.** At a measured 15 ms
   RTT to us-east-1 that caps throughput near 667 PUT/s regardless of bandwidth.
   Config-only fix, no code: set 100–200 in `~/.aws/config`.
2. **Crump rewrote every file every run.** Content was byte-identical but every
   mtime changed, and sync compares size + mtime — so everything looked newer.

### Churn, measured

`status_date` shows **355,749 entities changed status in 2026 across ~34 weeks —
about 10,463/week, or 0.50%.** Allowing for new registrations, address changes
and newly-geocoded addresses, 1–3% is a fair upper bound: **~20–60k files a week
instead of 2 million.**

- [x] **Content-aware writes.** `Atomizer` compares the serialized record
      against the file on disk and skips identical ones, leaving mtime intact.
- [x] **Writes deferred to `flush()`.** This was the subtle part. The SCC ships
      several rows per entity when agent/merger history differs, so writing as
      rows arrived let an *intermediate* row hit disk — and which one won varied
      between runs. Result: **460 files oscillated on every run forever**,
      re-uploading indefinitely. Buffering each entity's final content and
      writing once at the end fixed it. Verified: **0.00% churn, 0 files
      differing, stable across three consecutive runs.**
- [x] **Guarded `--prune`** (step 3). Deletes entity files absent from the feed,
      locally and via `--delete` on the sync. Crump cannot distinguish "the SCC
      removed this" from "the download truncated", so pruning is refused after a
      `--limit` or `--files` run, and refused when more than `--prune-limit`
      percent look stale (5% default). Both guards verified: it declined a
      limited run, pruned one genuinely stale file, and **refused a 150,000-file
      injection at 6.8% with an explanatory message.**
- [x] **Churn reporting** (step 4): `20,933 changed, 2,072,410 unchanged (1.00%
      churn)`, with a warning above 50% since that signals a format change
      rather than real data movement.
- [x] **`--force-rewrite`** for when the output format genuinely changes.
- [x] **19 new tests**; **254 passing** overall.

### Full-scale results

| | Before | After |
|---|---|---|
| Files rewritten (unchanged data) | 2,093,343 | **0** |
| Churn reported | — | **0.00%** |
| Run time | 203 s | 178 s (cold) / 187 s (steady) |

### Memory: fixed (2026-08-27)

The first implementation peaked at **2.70 GB**, which I wrongly called "fine on
the Ubuntu server" without checking — the server has **1 GB RAM + 1 GB swap**, so
it would have thrashed or OOMed. Two separate consumers, both now fixed:

| Configuration | Peak RSS |
|---|---|
| baseline, no atomize | 0.04 GB |
| atomize, buffer-everything (first attempt) | **2.70 GB** |
| atomize, deferred buffering only | 1.12 GB |
| + related records on disk | **0.31 GB** |
| **full pipeline (`-a -L`, CSV + JSON)** | **0.51 GB** |

- [x] **Deferred buffering.** A 5-second pre-pass (`repeated_ids()`) reads just
      the ID column to find the **36,658 entities (1.8%)** that appear on more
      than one source row. Only those are buffered — the rest stream straight to
      disk. Preserves the last-row-wins determinism that stopped the 460-file
      oscillation. 2.2 GB → 0.23 GB.
- [x] **Related records moved to a temporary SQLite index**
      (`crumplib/related.py`). The four files total ~1.95 M rows and cost
      ~850 MB as a dict. Batched inserts, index built after loading, one
      indexed query per entity. Temp file deleted on close; verified no
      leftovers. Costs ~169 MB of disk for Officer.csv.
      `group_related()` deleted as dead code.
- [x] **Verified**: 0.00% churn on a rerun of all 2,049,921 files, and output
      byte-identical to the in-memory version (spot-checked a document with 326
      nested related records).
- [x] **Audited the other tools** rather than assuming: `db_load` batches 10,000
      rows and only holds per-table column lists; `geocode -b` peaks at **219 MB**
      on the largest file (771,923 pending addresses). Both fit.

### Still config, not code

- [ ] **Raise `max_concurrent_requests`** in `~/.aws/config` to 100–200. This is
      the other half of the speedup and needs no code change:
      ```ini
      [default]
      s3 =
          max_concurrent_requests = 200
          max_queue_size = 10000
      ```
      Also worth evaluating `s5cmd`, a Go client typically several times faster
      than the Python CLI on small-object workloads.

---

## Phase 12 — Weekly scheduling — COMPLETE

- [x] **`bin/weekly`** — wrapper doing the full update: `crump -d -a -L --publish`,
      then `db_load --upload`, then batch geocoding of each entity file.
- [x] **`deploy/crontab.example`** — `0 1 * * 0`, i.e. **1 AM every Sunday**. Verified
      the field order and that cron weekday 0 is Sunday; next firings land on
      2026-08-30, 09-06, 09-13.
- [x] **Quiet by default.** Crump prints a per-address progress character, so a
      naive cron job would mail two million characters weekly. The script logs
      everything to `logs/weekly-<date>.log` and echoes only a summary plus any
      failure, via a saved file descriptor.
- [x] **Layout settled (2026-08-27).** First attempt put `weekly` in `deploy/`,
      which conflated two different things: `deploy/` is what you install once,
      whereas `weekly` runs every week forever. Final split:
      | | |
      |---|---|
      | `bin/` | `crump`, `geocode`, `db_load`, `weekly` — the executables |
      | `deploy/` | `crontab.example`, `aws-config.example`, `README.md` — install-time config |
      Consequences handled: the CLIs gained a small `sys.path` bootstrap so they
      still run from a checkout without `pip install`; `weekly` invokes them by
      absolute path from `$BIN` while working from the repo root; CI, the main
      README, the crontab, and `tests/test_geocode_cli.py` all updated. The test
      loader now supplies `__file__`, which the bootstrap needs.
- [x] **`deploy/aws-config.example`** — the `max_concurrent_requests = 200`
      setting that publishing depends on, which until now existed only in
      conversation.
- [x] **`deploy/README.md`** — setup, resource requirements (~510 MB peak
      memory, ~10 GB disk), and what to do when a run fails.
- [x] **Locked.** `flock` prevents a second run starting on top of one that
      overran; skipped gracefully where `flock` is absent (macOS development).
- [x] **Geocoding is best-effort** — a third-party API failure is noted in the
      log but does not fail the run, since successful geocodes are already
      cached for next week.
- [x] **Log rotation** — logs older than `CRUMP_KEEP_LOGS` days (default 56) are
      deleted, so `logs/` cannot grow without bound.
- [x] **Explicit `PATH`** in the crontab: cron's minimal environment otherwise
      fails to find `aws` and `python3` even when an interactive shell finds
      them. This is the most common reason a working command fails under cron.

### Not verified end-to-end

- [ ] The wrapper has not been run start-to-finish; only its syntax and the cron
      schedule were checked. The first real Sunday run is the test. If it fails,
      `logs/weekly-<date>.log` holds the full output and the cron mail names the
      step that failed.

---

## Phase 13 — OOM on the 1 GB server (2026-08-31)

The first real weekly run was **Killed** by the OOM killer, during
`ReservedName.csv`. My earlier "510 MB peak" was measured on a Mac with tens of
gigabytes free, where nothing forces the issue.

Measured the components directly with `tracemalloc` rather than inferring from
RSS, which is what I should have done the first time:

| Component | Cost |
|---|---|
| `repeated_ids()` pre-pass | **172 MB peak** (transient) |
| `GeocodeCache` preload | **104 MB**, and grows with every geocode |
| `JurisdictionIndex` | **76 MB** |
| Python, buffers, everything else | ~110 MB |

No single bug — four things stacking, plus `--publish` capturing two million
lines of `aws s3 sync` output on top.

- [x] **Geocode cache preload is now opt-in.** It loaded every address hash into
      a set to skip a SQL round trip. Measured: 104 MB for 3.5x faster lookups
      (72,700/s vs 21,000/s). At 21,000/s the SQL path costs about three extra
      minutes on a full run — a good trade against an OOM. Also note the cost
      *grows*: it was 30 MB when written, 104 MB now, and rising with every
      address geocoded.
- [x] **`repeated_ids()` stores fingerprints, not strings.** 172 MB → 150 MB.
      A hash collision would only mean an entity is buffered unnecessarily,
      which is harmless.
- [x] **`aws s3 sync` output is streamed, not captured.** `capture_output=True`
      buffered a line per object: ~260 MB for two million files, arriving right
      at peak. Now keeps only the last 20 lines, which is all that was ever
      displayed.
- [x] **Entity ids are only retained when `--prune` needs them** (~170 MB).
- [x] **Result: 474 MB → 314 MB peak**, comfortably inside 1 GB.

### What I got wrong

- I reported "510 MB, fine on a 1 GB server" from a macOS measurement, having
  earlier been told the server has 1 GB RAM and 1 GB swap. A number measured
  where nothing constrains it is not evidence about a constrained machine.
- My first diagnosis this round (entity ids) saved 10 MB of the 160 needed. I
  should have measured the components before changing anything.

### Still to watch

- [ ] **The geocode cache set grows with the corpus.** Preload is off now, so
      this is bounded — but `GeocodeCache` is still constructed per run and
      SQLite's page cache will grow. Worth re-measuring after the backfill
      finishes.
- [ ] **Peak is 314 MB against 1 GB.** Comfortable, not luxurious. Adding
      another in-memory index would need measuring first, on the server.
