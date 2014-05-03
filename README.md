# Crump

A parser for [the Virginia State Corporation Commission's business entity records](https://www.scc.virginia.gov/clk/purch.aspx), which are provided as a single, enormous fixed-width file. Named for Beverley T. Crump, the first member of the State Corporation Commission.

[The file layout](https://www.scc.virginia.gov/clk/files/layout_be.pdf) is documented on the SCC's website as a PDF generated from an ASCII file. (Also available as [not-entirely-formatted ASCII](record_layouts.txt).)

[A sample data file](http://s3.amazonaws.com/data.openva.com/corporations/2014-04-30.zip) is available.

## To Do

* [x] Create a tool that will break the file up into its 9 constituent files, which have been rudely concatenated into a single file. This is probably best done in sed or AWK, and can be done based on the length of each line, since each table has, luckily, a unique column count.</del>
* [x] [Create a machine-readable mapping of column positions to column names, by file](http://github.com/openva/crump/issues/4).
* [ ] Figure out what "tables" are and how those come into play. (Those are listed in file 1.) I'm pretty sure that the tables are lookup tables, e.g., to map `WV` to `West Virginia`, among many other less-obvious things.
* [x] Create a tool that will turn each of the 9 data files into CSV and JSON. (The former may well be the output from the AWK recipes.)
* [ ] Script the retrieval of the file (updated weekly, shortly after 1:00 AM on Wednesdays) and storage of it at a stable URL, plus archiving of past versions.
* [ ] Create an importer that will load this data into Elasticsearch.
* [ ] Create a website to search for, retrieve, display records.
