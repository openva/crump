# Deploying Crump

Configuration for running Crump on a server. Nothing here is needed to use
Crump locally.

The weekly job itself is [`bin/weekly`](../bin/weekly), alongside the other
executables — it runs every week, rather than at deploy time.

| File | |
|---|---|
| [`crontab.example`](crontab.example) | Schedules it for 1 AM every Sunday |
| [`aws-config.example`](aws-config.example) | AWS CLI settings; the concurrency one matters a lot |

## Setup

```sh
git clone https://github.com/openva/crump.git
cd crump

# Crump needs only PyYAML and requests, both packaged by Debian and Ubuntu.
sudo apt install python3-yaml python3-requests

aws s3 cp s3://data.vabusinesses.org/addresses.db .

cat deploy/aws-config.example >> ~/.aws/config   # then edit as needed
crontab -e                                       # paste crontab.example

./bin/weekly                                     # first run, by hand
```

There is no install step: the scripts in `bin/` locate the `crumplib` package
relative to themselves, so a clone runs as-is.

Do not skip `addresses.db`. Everything else rebuilds from the SCC feed, but that
file holds years of accumulated geocoding — without it Crump still runs, and
produces no coordinates, no FIPS codes, and no locality files.

### Why apt rather than pip

On Ubuntu 24.04 and other PEP 668 systems, `pip install` into the system Python
fails with `externally-managed-environment`. That is deliberate: pip and apt
would otherwise fight over the same files. Installing the two dependencies from
apt sidesteps it entirely.

`--break-system-packages` also works, and is a bad idea on a server running an
unattended job — it lets pip write into a Python that apt also manages.

### Running the tests

```sh
sudo apt install python3-pytest
cd /home/ubuntu/crump && pytest
```

Run from the repository root: the tests read `table_maps/` by relative path.
No install is needed — `pyproject.toml` puts the root on `sys.path`.

A virtual environment also works, and is the only way to get `ruff`, which apt
does not package:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

It does not change how `bin/weekly` runs, since the scripts find `crumplib`
themselves.

## What the weekly run does

1. Downloads the current SCC export and normalizes it
2. Writes per-entity JSON and per-locality CSVs
3. Publishes both to S3
4. Builds the SQLite database and uploads it
5. Geocodes addresses that are not yet cached, in batches

Everything is logged to `logs/weekly-<date>.log`. Only a summary and any
failure go to stdout, which is what cron mails.

## Requirements

Modest. Peak memory is about 315 MB, so a 1 GB server is enough. Disk is the
larger need: roughly 1 GB for the extracted CSVs, 8 GB for the per-entity JSON,
1.2 GB for the database, and 100 MB for the locality files.

A full run takes well under an hour once the geocode cache is populated.

## Environment

| Variable | Default | |
|---|---|---|
| `CRUMP_BUCKET` | `data.vabusinesses.org` | Where to publish |
| `CRUMP_LOG_DIR` | `logs` | Where logs go |
| `CRUMP_KEEP_LOGS` | `56` | Days of logs to keep |

## If a run fails

The cron mail names the step that failed and points at the log. Runs are
independent — a failed week is fixed by the next one, or by running
`bin/weekly` by hand. Geocoding is best-effort and never fails the run,
since anything already geocoded is cached.
