#!/bin/bash

# Retrieve the ZIP File.
#curl -o cisbemon.zip https://www.scc.virginia.gov/SCC-INTERNET/clk/data/CISbemon.CSV.zip

# Unzip it to a directory and erase the ZIP file.
#unzip cisbemon.zip cisbemon
#rm cisbemon.zip

cd cisbemon || exit

# These files have hundreds of invalid characters. Strip them out.
echo "Removing invalid characters from all CSV files"
for f in *.csv
do
	cat "$f" |iconv -f ISO-8859-1 -c > "$f"-new
	rm -f "$f"
	mv "$f"-new "$f"
done

# Make all filenames lowercase, since they determine database table names.
for i in $(find . -type f -name "*[A-Z]*")
do
	mv "$i" "$(echo $i | tr A-Z a-z)"
done

# Insert each file into SQL.
## TO DO: CHANGE THIS TO MYSQL. USE AN ENV VARIABLE FOR THE DSN.
## http://csvkit.readthedocs.io/en/1.0.2/scripts/csvsql.html?highlight=mysql
echo "Loading each file into the database"
for f in *.csv
do
	echo "$f"
	csvsql --db sqlite:///businesses.db --insert "$f"
done
