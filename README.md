# Crump

A parser for [the Virginia State Corporation Commission's business entity records](https://www.scc.virginia.gov/clk/purch.aspx), which are provided as a single, enormous fixed-width file. Named for Beverley T. Crump, the first member of the State Corporation Commission.

[The file layout](https://www.scc.virginia.gov/clk/files/layout_be.pdf) is documented on the SCC's website as a PDF generated from an ASCII file. (Also available as [not-entirely-formatted ASCII](record_layouts.txt).)

[A sample data file](http://s3.amazonaws.com/data.openva.com/corporations/2014-04-23.zip) is available.

## To Do

* Create a tool that will break the file up into its 9 constituent files, which have been rudely concatenated into a single file. This is probably best done in sed or AWK, and can be done based on the length of each line, since each table has, luckily, a unique column count.
* Create a tool that will turn each of the 9 files into CSV and JSON.
* Figure out what "tables" are and how those come into play. (Those are listed in file 1.) I'm pretty sure that the tables are lookup tables, to maps `WV` to `West Virginia`, among a bunch of other things.
* Create an importer that will load this data into Elasticsearch.
* Create a website to search for, retrieve, display records.
