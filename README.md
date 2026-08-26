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

For general purposes, `./crump -dg` is the best way to invoke Crump. That downloads the current data file and attaches coordinates to every address already in the cache.

## Installation

```sh
pip install -r requirements.txt
```

Requires Python 3.11 or newer.

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
./crump -dga --publish data.vabusinesses.org
```

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
./crump -dj      # download, geocode, and assign jurisdictions
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

## A SQLite database

`db_load` reads the normalized CSVs and builds a single queryable database:

```sh
./crump -dg      # download and normalize
./db_load        # build crump.db
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
./db_load --upload data.vabusinesses.org
```

That is a deliberate, separate step. A failed upload never means rebuilding the
database, and nothing uploads unless you ask.

## Geocoding

`crump -g` attaches coordinates for any address already in `addresses.db`. To geocode the addresses that aren't yet cached, run `geocode` against Crump's output:

```sh
./geocode -i output/corp.csv              # principal office addresses
./geocode -i output/corp.csv -p agent_    # registered agent addresses
```

Virginia addresses are geocoded by [the VGIN composite locator](https://vginmaps.vdem.virginia.gov/); everything else goes to [the Census geocoder](https://geocoding.geo.census.gov/). Results and failures are both cached, so re-running only attempts addresses it hasn't seen.

The bundled cache holds about 565,000 addresses geocoded in 2014–15, which covers roughly a fifth of the unique addresses in the current data.

### Batch geocoding

Geocoding a million addresses one request at a time takes weeks. The `-b` flag
sends them to the Census Bureau's batch endpoint instead, 10,000 at a time:

```sh
./geocode -i output/corp.csv -b
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
pip install -e '.[dev]'   # the package plus pytest and ruff

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
