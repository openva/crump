#/bin/bash

# By Stefan Farestam
# http://stackoverflow.com/questions/5014632/how-can-i-parse-a-yaml-file-from-a-linux-shell-script#answer-21189044
function parse_yaml {
   local prefix=$2
   local s='[[:space:]]*' w='[a-zA-Z0-9_]*' fs=$(echo @|tr @ '\034')
   sed -ne "s|^\($s\):|\1|" \
        -e "s|^\($s\)\($w\)$s:$s[\"']\(.*\)[\"']$s\$|\1$fs\2$fs\3|p" \
        -e "s|^\($s\)\($w\)$s:$s\(.*\)$s\$|\1$fs\2$fs\3|p"  $1 |
   awk -F$fs '{
      indent = length($1)/2;
      vname[indent] = $2;
      for (i in vname) {if (i > indent) {delete vname[i]}}
      if (length($3) > 0) {
         vn=""; for (i=0; i<indent; i++) {vn=(vn)(vname[i])("_")}
         printf("%s%s%s=\"%s\"\n", "'$prefix'",vn, $2, $3);
      }
   }'
}

# Create an output directory
OUTPUT_DIR="output"
mkdir -p $OUTPUT_DIR

# Determine the length of the file, since we'll need this later. It's so that we can search
# the first half of the file for Limited Partnerships and the second half for Limited Liability
# Companies.
FILE_LENGTH=`wc -l cisbemon.txt |cut -d " " -f 2`
HALF_LENGTH=`echo "$FILE_LENGTH/2" | bc`

# File 1, in the order of the master file
echo Table File
awk 'length() == 65' cisbemon.txt > $OUTPUT_DIR/1_tables.txt;

# File 2, in the order of the master file
echo Corporate File
awk 'length() == 674' cisbemon.txt > $OUTPUT_DIR/2_corporate.txt;

# File 3, in the order of the master file
echo Limited Partnership File
head -$HALF_LENGTH cisbemon.txt | awk 'length() == 508' > $OUTPUT_DIR/3_lp.txt;

# File 4, in the order of the master file
echo Corporate/Limited Partnership/Limited Liability Company File
awk 'length() == 182' cisbemon.txt > $OUTPUT_DIR/4_amendments.txt;

# File 5, in the order of the master file
echo Corporate Officer File
awk 'length() == 95' cisbemon.txt > $OUTPUT_DIR/5_officers.txt;

# File 6, in the order of the master file
echo Corporate/Limited Partnership/Limited Liability Company Name File
awk 'length() == 120' cisbemon.txt > $OUTPUT_DIR/6_name.txt;

# File 7, in the order of the master file
echo Merger File
awk 'length() == 126' cisbemon.txt > $OUTPUT_DIR/7_merger.txt;

# File 8, in the order of the master file
echo Corporate/Limited Partnership/Limited Liability Company Reserved/Registered Name File
awk 'length() == 335' cisbemon.txt > $OUTPUT_DIR/8_registered_names.txt;

# File 9, in the order of the master file
#
# The line length is exactly the same as the LP file, so we can't simply create the file based
# on line length. Instead, we only check the latter half of the file for lines of this length.
echo Limited Liability Company File
tail -$HALF_LENGTH cisbemon.txt |awk 'length() == 508' > $OUTPUT_DIR/9_llc.txt;

# Turn File 1 into structured data
echo Converting Table File into Tabular Data
awk '{
one=substr($0,0,2)
two=substr($0,3,2)
three=substr($0,5,10)
four=substr($0,15,50)
printf ("%s|%s|%s|%s\n", one, two, three, four)
}' $OUTPUT_DIR/1_tables.txt > 1_tables.csv
