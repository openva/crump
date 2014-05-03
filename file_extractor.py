#!/usr/bin/env python

# TO DO
# * Add sanity checks -- make sure that we have read and write permissions.
# * Make sure that files and directories exist. If they don't, create them.
# * Add functionality to break up files, as is being done in in the shell script.
# * If the master file doesn't exist, retrieve it from S3.

# Set some variables up front.
master_file = "cisbemon.txt"
output_dir = "output"

# Requires PyYAML <http://pyyaml.org/>
import yaml
import csvkit
import os
import glob
import subprocess
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


# Iterate through all of the YAML table maps and turn them into CSV.
os.chdir("table_maps/")
csv_header = "column,start,length\n"
for file in glob.glob("*.yaml"):
	stream = open(file, 'r')
		
	# Import the data from YAML.
	field_map = yaml.load(stream)
	
	# Open a new file to write to.
	with open(file.replace(".yaml", "") + ".csv", "w") as csv_file:
		
		csv_file.write(csv_header)
		
		# Iterate through every YAML entry and write it to our CSV file.
		for field in field_map:
			line = field['name'] + "," + str(field['start']) + "," + str(field['length']) + "\n"
			csv_file.write(line)

# Now apply each CSV table map to each file.

# Open each table map and run in2csv to convert the files.
for file in glob.glob("*.csv"):
	# TODO: Get a list of all files in /output/, and match up files on the basis of numbered prefix.
	# TODO: Actually run the below with subprocess, rather than printing it.
	print "in2csv -f fixed -s " + file + " ../output/1_tables.txt"
	
	# Delete the CSV version of this table map (leaving the YAML version).
	os.remove(file)
	