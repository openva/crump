#!/bin/bash

cat $1 | awk 'length($0) == 65' > 1_table.txt
cat $1 | awk 'length($0) == 674' > 2_corporate.txt
cat $1 | awk 'length($0) == 508' > 3_limited_partnership.txt
cat $1 | awk 'length($0) == 182' > 4_corporate_ltd_llc.txt
cat $1 | awk 'length($0) == 95' > 5_corporate_officer.txt
cat $1 | awk 'length($0) == 120' > 6_corporate_ltd_llc_name.txt
cat $1 | awk 'length($0) == 126' > 7_merger.txt
cat $1 | awk 'length($0) == 335' > 8_corporate_ltd_llc_reserved_registered_name.txt
cat $1 | awk 'length($0) == 508' > 9_ltd_compant.txt