#!/usr/bin/env python

# TO DO
# * Add sanity checks -- make sure that we have read and write permissions.
# * Make sure that files and directories exist. If they don't, create them.
# * If the master file doesn't exist, retrieve it from S3.

# Set some variables up front.
master_file = "cisbemon.txt"
output_dir = "output"

# Requires PyYAML <http://pyyaml.org/>
import yaml
import csvkit
import os
import errno
import glob
import subprocess
import math

# Create the output directory.
try:
	os.makedirs(output_dir)
except OSError as exception:
	if exception.errno != errno.EEXIST:
		raise

# Count the number of lines in the master file.
with open(master_file) as f:
	for i, l in enumerate(f):
		pass
	line_count = i + 1

# File 1
print "Extracting Table File"
subprocess.call("awk 'length() == 65' cisbemon.txt > " + output_dir + "/1_tables.txt", shell=True);

# File 2
print "Extracting Corporate File"
subprocess.call("awk 'length() == 674' cisbemon.txt > " + output_dir + "/2_corporate.txt", shell=True);

# File 3
print "Extracting Limited Partnership File"
subprocess.call("head -" + str(int(math.floor(line_count / 2))) + " cisbemon.txt | awk 'length() == 508' > " + output_dir + "/3_lp.txt", shell=True);

# File 4
print "Extracting Corporate/Limited Partnership/Limited Liability Company File"
subprocess.call("awk 'length() == 182' cisbemon.txt > " + output_dir + "/4_amendments.txt", shell=True);

# File 5
print "Extracting Corporate Officer File"
subprocess.call("awk 'length() == 95' cisbemon.txt > " + output_dir + "/5_officers.txt", shell=True);

# File 6
print "Extracting Corporate/Limited Partnership/Limited Liability Company Name File"
subprocess.call("awk 'length() == 120' cisbemon.txt > " + output_dir + "/6_name.txt", shell=True);

# File 7
print "Extracting Merger File"
subprocess.call("awk 'length() == 126' cisbemon.txt > " + output_dir + "/7_merger.txt", shell=True);

# File 8
print "Extracting Corporate/Limited Partnership/Limited Liability Company Reserved/Registered Name File"
subprocess.call("awk 'length() == 335' cisbemon.txt > " + output_dir + "/8_registered_names.txt", shell=True);

# File 9
# The line length is exactly the same as the LP file, so we can't simply create the file based
# on line length. Instead, we only check the latter half of the file for lines of this length.
print "Extracting Limited Liability Company File"
subprocess.call("tail -" + str(int(math.floor(line_count / 2))) + " cisbemon.txt |awk 'length() == 508' > " + output_dir + "/9_llc.txt", shell=True);

# Iterate through all of the YAML table maps and turn them into CSV.
os.chdir("table_maps/")
csv_header = "column,start,length\n"
for file in glob.glob("*.yaml"):
	stream = open(file, 'r')
		
	# Import the data from YAML.
	field_map = yaml.load(stream)
	
	# Open a new file to write to.
	with open(file.replace(".yaml", ".csv"), "w") as csv_file:
		
		csv_file.write(csv_header)
		
		# Iterate through every YAML entry and write it to our CSV file.
		for field in field_map:
			line = field['name'] + "," + str(field['start']) + "," + str(field['length']) + "\n"
			csv_file.write(line)

# Now apply each CSV table map to each file. Open each table map and run in2csv to convert the files.
for file in glob.glob("*.csv"):
	subprocess.call("in2csv -e us-ascii-f fixed -s " + file + " ../output/" + file.replace(".csv", ".txt") + " > ../output/" + file, shell=True);
	
	# Delete the CSV version of this table map (leaving the YAML version).
	os.remove(file)
	