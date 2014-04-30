#/bin/bash

# Create an output directory
mkdir -p $2

# Determine the length of the file, since we'll need this later. It's so that we can search
# the first half of the file for Limited Partnerships and the second half for Limited Liability
# Companies.
#
# TO DO: We're faking this right now, manually setting the length of one half of the file. That's
# because rounding numbers in Bash turns out to be surprisingly difficult.
FILE_LENGTH=`wc -l cisbemon.txt |cut -d " " -f 2`
HALF_LENGTH=891210

# File 1, in the order of the master file
echo Table File
awk 'length() == 65' cisbemon.txt > $2/1_tables.txt;

# File 2, in the order of the master file
echo Corporate File
awk 'length() == 674' cisbemon.txt > $2/2_corporate.txt;

# File 3, in the order of the master file
echo Limited Partnership File
head -$HALF_LENGTH cisbemon.txt | awk 'length() == 508' > $2/3_lp.txt;

# File 4, in the order of the master file
echo Corporate/Limited Partnership/Limited Liability Company File
awk 'length() == 182' cisbemon.txt > $2/4_amendments.txt;

# File 5, in the order of the master file
echo Corporate Officer File
awk 'length() == 95' cisbemon.txt > $2/5_officers.txt;

# File 6, in the order of the master file
echo Corporate/Limited Partnership/Limited Liability Company Name File
awk 'length() == 120' cisbemon.txt > $2/6_name.txt;

# File 7, in the order of the master file
echo Merger File
awk 'length() == 126' cisbemon.txt > $2/7_merger.txt;

# File 8, in the order of the master file
echo Corporate/Limited Partnership/Limited Liability Company Reserved/Registered Name File
awk 'length() == 335' cisbemon.txt > $2/8_registered_names.txt;

# File 9, in the order of the master file
#
# The line length is exactly the same as the LP file, so we can't simply create the file based
# on line length. Instead, we count the number of lines in files 1, 2, and 3, and only look at
# the files in the file subsequent to that.
echo Limited Liability Company File
tail -$HALF_LENGTH cisbemon.txt |awk 'length() == 508' > $2/9_llc.txt;
