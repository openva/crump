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
import json


def main():
    # Create the output directory.
    try:
        os.makedirs(output_dir)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise

    field_maps = {}

    for csv_file in glob.glob("table_maps/*.yaml"):
        stream = open(csv_file, 'r')

        # Import the data from YAML.
        field_map = yaml.load(stream)

        head, tail = os.path.split(csv_file)

        map_id = tail[0]
        field_maps[map_id] = {}
        field_maps[map_id]["map"] = field_map
        field_maps[map_id]["name"] = tail

    # Count the number of lines in the master file.
    last_file = ""
    current_map = None
    csv_writer = None
    json_file = None
    with open(master_file) as f:
        for current_line in enumerate(f):
            file_number = current_line[1][1]
            if file_number in field_maps:
                if file_number != last_file:
                	# Terminate the prior JSON file by removing the trailing comma and adding a bracket.
                    if last_file != "":
                        json_file.seek(-1, os.SEEK_END)
                        json_file.truncate()
                        json_file.write(']')
                    # new file - grab proper field map and do file setup
                    current_map = field_maps[file_number]["map"]
                    current_name = field_maps[file_number]["name"]
                    csv_name = current_name.replace(".yaml", ".csv")
                    json_name = current_name.replace(".yaml", ".json")
                    last_file = file_number
                    csv_file = open("output/"+csv_name, 'wb')
                    json_file = open("output/"+json_name, 'wb')
                    field_names = []
                    for field in current_map:
                        field_names.append(field["name"])
                    field_tuple = tuple(field for field in field_names)
                    csv_writer = csvkit.DictWriter(csv_file, field_tuple)
					
                    csv_writer.writeheader()
                    print "Creating",csv_name.replace(".csv","")
                    # Start a new JSON file with an opening bracket.
                    json_file.write('[')
                # break the line out into pieces
                line = {}
                for field in current_map:
                    start = int(field["start"])
                    length = int(field["length"])
                    name = field["name"]
                    end = start + length
                    line[name] = current_line[1][start:end].strip()
                try:
                    csv_writer.writerow(line)
                except UnicodeDecodeError as exception:
                    print "Found an incorrect character in",line,"and hopefully fixed it."
                    for key in line:
                        line[key] = remove_non_ascii(line[key])
                    csv_writer.writerow(line)
                json.dump(line,json_file)
                # Add a separating comma between elements.
                json_file.write(',')
# From http://stackoverflow.com/a/1342373/3579517 with slight modification to replace with space
def remove_non_ascii(s):
    return "".join(i if ord(i)<128 else " " for i in s )

if __name__ == "__main__":
    main()
