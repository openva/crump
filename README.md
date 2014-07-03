# Crump

A parser for [the Virginia State Corporation Commission's business entity records](https://www.scc.virginia.gov/clk/purch.aspx), which are provided as a single, enormous fixed-width file. Named for Beverley T. Crump, the first member of the State Corporation Commission.

Crump retrieves the current SCC records (updated weekly) and turns them into CSV and JSON. Alternately, it can improve the quality of the data (formatting dates, ZIP codes, replacing internal status codes with human-readable translations, etc.), atomize the data into millions of individual JSON files, or create [Elasticsearch-compatible bulk API data](elasticsearch.org/guide/en/elasticsearch/reference/current/docs-bulk.html).

The most recent copy of the raw SCC data can be found at [https://s3.amazonaws.com/virginia-business/current.zip](https://s3.amazonaws.com/virginia-business/current.zip).

## Usage

```
crump [-h] [-a] [-i file.txt] [-o output_dir] [-t] [-d] [-e]

  -h, --help            show this help message and exit
  -a, --atomize         generate millions of per-record JSON files
  -i file.txt, --input file.txt
                        raw SCC data (default: cisbemon.txt)
  -o output_dir, --output output_dir
                        directory for JSON and CSV
  -t, --transform       format properly date, ZIP, etc. fields
  -d, --download        download the data file, if missing
  -e, --elasticsearch   create Elasticsearch bulk API data
```

For general purposes, `./crump -td` is probably the best way to invoke Crump. This will download the current data file and transform the data to make it adhere to basic data quality norms.


# License
Released under [the MIT License](https://github.com/openva/crump/blob/master/LICENSE).
