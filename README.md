# Crump

A parser for [the Virginia State Corporation Commission's business entity records](https://cis.scc.virginia.gov/), which are published as a ZIP of CSV files. Named for Beverley T. Crump, the first member of the State Corporation Commission.

Crump downloads the current SCC records, normalizes them, and emits clean CSV and JSON. Normalizing means: stripping the fixed-width padding the CSVs still carry, parsing dates and share counts, expanding the status codes the SCC leaves raw, and attaching latitude and longitude from a cache of geocoded addresses.

## Usage

```
options:
  -h, --help            show this help message and exit
  -i dir, --input dir   directory holding the SCC CSVs (default: data)
  -o dir, --output dir  directory for JSON and CSV (default: output)
  -d, --download        download and extract the current data file
  -g, --geocode         attach coordinates from the geocoded address cache
  --cache file          geocoded address cache (default: addresses.db)
  --maps dir            directory of YAML field maps (default: table_maps)
  --json {array,lines,none}
                        JSON output format (default: lines)
  --no-csv              skip CSV output
  -a, --atomize         write one JSON file per entity, for a static API
  --atomize-dir dir     where per-entity JSON goes (default: <output>/entity)
  --atomize-indent n    indent per-entity JSON by n spaces (default: compact)
  --no-related          when atomizing, omit officers, names, amendments, mergers
  --publish bucket      sync atomized JSON to this S3 bucket (implies -a)
  --publish-prefix path key prefix within the bucket (default: entity)
  --publish-dry-run     show what would be uploaded, without uploading
  -l n, --limit n       stop after n records per file (for testing)
  -f stem [stem ...], --files stem [stem ...]
                        only process these maps, e.g. corp llc
```

For general purposes, `./bin/crump -dg` is the best way to invoke Crump. That downloads the current data file and attaches coordinates to every address already in the cache.

## Installation

Crump needs Python 3.12 or newer and two libraries. There is no install step —
the scripts in `bin/` find the `crumplib` package relative to themselves, so a
clone runs as-is.

On Debian or Ubuntu:

```sh
sudo apt install python3-yaml python3-requests
```

Elsewhere, or in a virtual environment:

```sh
pip install -r requirements.txt
```

Note that `pip install` into the system Python fails on Ubuntu 24.04 and other
PEP 668 systems with `externally-managed-environment`. Use apt, or a virtual
environment. See [`deploy/`](deploy/) for server setup.

## The data

The SCC publishes eleven CSVs, refreshed weekly, totaling about a gigabyte uncompressed:

| File | Contents |
|---|---|
| `Corp.csv` | Stock and nonstock corporations |
| `LLC.csv` | Limited liability companies |
| `LP.csv` | Limited partnerships |
| `GP.csv` | General partnerships |
| `BT.csv` | Business trusts |
| `PSA.csv` | Professional stock associations |
| `Amendment.csv` | Amendments to entity filings |
| `Merger.csv` | Mergers between entities |
| `Officer.csv` | Officers and directors |
| `NameHistory.csv` | Prior and fictitious names |
| `ReservedName.csv` | Reserved and registered names |

Crump writes one output file per input, using its own cleaner column names — `corp.csv` and `corp.jsonl` from `Corp.csv`, and so on.

### Field maps

Each input file has a YAML map in [`table_maps/`](table_maps/) describing its fields: the upstream column name, the name Crump emits, a description, a type, and any code expansions. Maps are the place to change output names or document a field; no code changes are needed.

## A static API

`crump -a` writes one JSON file per entity, which makes a complete read-only API
that S3 can serve with no application behind it:

```sh
./bin/crump -d --publish data.vabusinesses.org
```

### Memory

Crump is built to run on a small server — peak usage is about 315 MB for the
full pipeline, including atomizing all 2 million entities. Two things keep it
there rather than in the gigabytes:

Related records (officers, name history, amendments, mergers) go into a
temporary SQLite index rather than a dict. Nearly two million rows in memory
cost ~850 MB; on disk they cost almost nothing and are looked up per entity.

Per-entity writes are deferred only for the ~1.8% of entities the SCC ships on
more than one row. Those must be buffered so the last row wins deterministically;
everything else streams straight to disk. Buffering every record instead would
cost ~2.2 GB.

### Incremental publishing

Crump only rewrites a per-entity file when its contents actually change, and
leaves unchanged files untouched — mtime included. That matters because
`aws s3 sync` decides what to upload by comparing size and modification time, so
a rewritten-but-identical file looks newer and uploads for nothing.

Only about 0.5% of entities change status in a given week, so a weekly run
typically rewrites a low single-digit percentage of files and the sync uploads
only those. Each run reports the churn:

```
Per-entity JSON in output/entity/: 20,933 changed, 2,072,410 unchanged (1.00% churn)
```

Unusually high churn is flagged, since it usually means the output format
changed rather than the data.

`--prune` deletes files for entities no longer in the feed, locally and on S3
(by adding `--delete` to the sync). It is heavily guarded: Crump cannot tell
"the SCC removed this entity" from "the download was truncated", so pruning is
refused after a `--limit` or `--files` run, and refused if more than
`--prune-limit` percent of entities look stale (5% by default).

`--force-rewrite` rewrites everything regardless, which is only needed if the
output format itself changed.

`--publish` publishes everything Crump produces — per-entity JSON under
`entity/` and locality CSVs under `localities/` — so it implies `-a` and `-L`,
and through them `-j` and `-g`. That means it needs the geocoded address cache
and takes a few minutes longer than a bare parse. Each artifact is served with
the right Content-Type, and only files of the expected type are uploaded, so
stray local files can never end up in a public bucket.

Each document holds the entity's own fields plus its related records — officers,
former and fictitious names, amendments, and mergers — so a single request
returns everything known about a business.

Files are sharded by the first four characters of the entity ID:

```
entity/1168/11683582.json
entity/T083/T0836306.json
```

Sharding is not cosmetic. There are about 2.1 million entities, and their IDs
cluster by the era they were issued; with a two-character shard, 40% of all files
landed in one directory. Four characters spreads them across ~2,100 directories
of a few thousand files each, which `aws s3 sync` and ordinary filesystem tools
can cope with.

Entity IDs are unique across all six entity types, so one flat namespace serves
every kind of business, and each document carries an `entity_type` field saying
which it is.

## Jurisdiction (city and county FIPS)

Virginia's 38 independent cities are not part of any county, so a business is in
either a county or a city, never both. The two can even share a name: Richmond
city (FIPS 51760) and Richmond County (51159) are sixty miles apart.

This cannot be read off an address. Measured against real data, a mailing
address of "Charlottesville" is inside Charlottesville city only about 46% of
the time — the rest are in surrounding Albemarle County. "Richmond" splits
across Richmond city, Chesterfield County, and Henrico County. And plenty of
addresses name a place that is not a jurisdiction at all, like Midlothian
(Chesterfield County) or Mechanicsville (Hanover County). Across a full run,
42% of businesses sit in a jurisdiction whose name differs from their mailing
city.

So Crump determines it geometrically, by testing the geocoded coordinates
against actual boundaries:

```sh
./bin/crump -dj      # download, geocode, and assign jurisdictions
```

That adds three columns to each entity: `fips`, `jurisdiction`, and
`jurisdiction_type` (`county` or `city`). They appear in the CSV, the JSON, the
per-entity files, and the SQLite database, and `fips` is indexed:

```sql
SELECT COUNT(*) FROM llc WHERE fips = '51059';   -- Fairfax County
```

`-j` implies `-g`, since the jurisdiction is derived from the coordinates. That
also means **geocoding coverage is the ceiling on jurisdiction coverage** — an
entity with no cached geocode gets no FIPS code. Businesses outside Virginia
correctly get none either.

Boundaries are the Census Bureau's TIGER data (2023), shipped in
[`boundaries/`](boundaries/) as a 2.6 MB file so lookups work offline and
reproducibly. Virginia's boundaries effectively never change, so the vintage is
pinned deliberately.

## Per-locality business lists

`-L` writes one CSV per Virginia county and independent city, intended for
municipal business-licensure departments checking the state's registrations
against their own license rolls:

```sh
./bin/crump -dL      # download, geocode, assign jurisdictions, write locality files
```

Files are named `<FIPS>-<Locality>.csv` — `51003-Albemarle-County.csv`,
`51760-Richmond-city.csv`. The FIPS code leads so files sort stably, and the
`County` / `city` suffix is kept because Fairfax, Franklin, Richmond and Roanoke
are each *both* a county and an independent city.

Each row is one business, with all six entity types merged into a single file
(hence the `entity_type` column):

| Column | |
|---|---|
| `id`, `entity_type`, `name` | which business, and what kind |
| `status`, `status_reason`, `status_date` | standing with the SCC |
| `incorporation_date` | when it was formed |
| `street_1`, `street_2`, `city`, `state`, `zip` | principal office |
| `latitude`, `longitude` | the geocoded point |

Registered agents, officers, and directors are deliberately excluded: an agent
is usually a law firm or a registered-agent service at an address unrelated to
where the business actually operates.

**Every status is included**, not just active businesses, so a department can
filter as it sees fit — an entity terminated last year may still owe a license
for the year it operated.

Note that a business only appears if its address could be geocoded, so these
lists are not a complete roster of businesses in a locality. Absence from a file
is not evidence that a business does not exist. `-L` implies `-j`, which implies
`-g`.

Add `--publish` to upload them:

```sh
./bin/crump -dL --publish data.vabusinesses.org    # to s3://.../localities/
```

## A SQLite database

`db_load` reads the normalized CSVs and builds a single queryable database:

```sh
./bin/crump -dg      # download and normalize
./bin/db_load        # build crump.db
```

The schema is generated from the field maps, so it tracks them automatically.
Dates are stored as ISO 8601 text, share counts as integers, and each geocoded
address becomes `<field>_latitude` and `<field>_longitude` REAL columns — so
bounding-box queries work and can use an index:

```sql
SELECT name, city FROM corp
 WHERE coordinates_latitude  BETWEEN 37.5 AND 37.6
   AND coordinates_longitude BETWEEN -77.5 AND -77.4;
```

The full dataset is about 4.1 million rows and loads in under a minute, giving a
1.2 GB database. Queries against it return in milliseconds.

Note that entity IDs are **not** unique within a table: the SCC ships multiple
rows per entity when registered-agent or merger history differs, and `db_load`
preserves all of them. Use `GROUP BY id` or `DISTINCT` if you want one row per
entity.

The database is a derived artifact. It is not checked into Git and building it
is not part of the build or CI — rebuild it whenever new weekly data lands.
To publish it:

```sh
./bin/db_load --upload data.vabusinesses.org
```

That is a deliberate, separate step. A failed upload never means rebuilding the
database, and nothing uploads unless you ask.

## Running weekly

The SCC refreshes its bulk export weekly.
[`bin/weekly`](bin/weekly) does a full update — download, normalize,
geocode, publish — and [`deploy/crontab.example`](deploy/crontab.example)
schedules it for 1 AM every Sunday:

```cron
0 1 * * 0    /home/ubuntu/crump/bin/weekly
```

The script logs everything to `logs/` and prints only a short summary, so what
cron mails you is worth reading rather than two million progress characters. It
takes a lock so a run that overruns a week cannot start a second copy on top of
itself, and geocoding is best-effort — a third-party API failing does not fail
the run, since whatever succeeded is cached for next time.

Override the defaults with `CRUMP_BUCKET`, `CRUMP_LOG_DIR`, or `CRUMP_KEEP_LOGS`
(days of logs to retain, default 56). See [`deploy/`](deploy/) for setup,
including the AWS CLI concurrency setting that publishing depends on.

## Geocoding

`crump -g` attaches coordinates for any address already in `addresses.db`. To geocode the addresses that aren't yet cached, run `geocode` against Crump's output:

```sh
./bin/geocode -i output/corp.csv              # principal office addresses
./bin/geocode -i output/corp.csv -p agent_    # registered agent addresses
```

While it runs, `geocode` prints one character per address and a key explaining
them:

```
+ geocoded  x no match  C cached  A no address  F failed before  ! API error
```

Use `-v` for a line of detail per address instead.

After ten consecutive API errors it stops, reporting the service, the last
error, and its type — enough to tell a DNS failure from a timeout from a
rate limit without re-running:

```
Stopping: 10 consecutive API errors.
  Service: https://vginmaps.vdem.virginia.gov/.../findAddressCandidates
  Last error: HTTPSConnectionPool(host='...', port=443): Max retries exceeded
  Error type: ConnectionError
```

Everything geocoded before the failure is already saved, so re-running picks up
where it stopped.

Virginia addresses are geocoded by [the VGIN composite locator](https://vginmaps.vdem.virginia.gov/); everything else goes to [the Census geocoder](https://geocoding.geo.census.gov/). Results and failures are both cached, so re-running only attempts addresses it hasn't seen.

The bundled cache holds about 565,000 addresses geocoded in 2014–15, which covers roughly a fifth of the unique addresses in the current data.

### Batch geocoding

Geocoding a million addresses one request at a time takes weeks. The `-b` flag
sends them to the Census Bureau's batch endpoint instead, 10,000 at a time:

```sh
./bin/geocode -i output/corp.csv -b
```

In testing, 1,000 addresses took about four seconds and matched 82% — the same
work would take seventeen minutes serially.

Virginia addresses still go to VGIN one at a time, because the state locator is
more accurate within Virginia than the national Census data. Pass `--batch-all`
to send everything through Census.

Batch results need more scrutiny than single lookups. The Census service
sometimes returns a near-match on a *different* street — asking for
`1 W Nationwide Blvd` and getting `1 E Nationwide Blvd` — which was about 1.2%
of matches in testing. Because a wrong coordinate is worse than a missing one,
those are rejected and recorded as failures. Use
`--allow-directional-conflicts` to keep them.

PO boxes and care-of lines are filtered out before submission; they never match,
and they would otherwise consume batch capacity.

## Development

```sh
python3 -m venv .venv                    # PEP 668 systems require one
.venv/bin/pip install -e '.[dev]'        # the package plus pytest and ruff
source .venv/bin/activate

pytest                  # tests
ruff check .            # lint
ruff format .           # apply formatting
ruff format --check .   # what CI enforces
```

Install with `-e` rather than just the dependencies: the tests import
`crumplib`, so the package has to be on the path. Without it they only work
when run from the repo root.

CI runs `ruff format --check`, which fails on unformatted code rather than
fixing it. Run `ruff format .` before pushing.

# License
Released under [the MIT License](https://github.com/openva/crump/blob/master/LICENSE).
