# Crump

A parser for [the Virginia State Corporation Commission's business entity records](https://www.scc.virginia.gov/clk/purch.aspx), which are provided as a single, enormous fixed-width file. Named for Beverley T. Crump, the first member of the State Corporation Commission.

Crump retrieves the current SCC records (updated weekly), cleans them up, and turns them into an API.

## Usage

docker build . --tag crump
docker run crump ./converter.sh

# License
Released under [the MIT License](https://github.com/openva/crump/blob/master/LICENSE).
