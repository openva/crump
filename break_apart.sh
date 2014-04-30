#!/bin/bash

mkdir -p $2

cat $1 | awk 'length($0) == 65' > $2/1_table.txt
cat $1 | awk 'length($0) == 674' > $2/2_corporate.txt
cat $1 | awk 'length($0) == 508' > $2/3_limited_partnership.txt
cat $1 | awk 'length($0) == 182' > $2/4_corporate_ltd_llc.txt
cat $1 | awk 'length($0) == 95' > $2/5_corporate_officer.txt
cat $1 | awk 'length($0) == 120' > $2/6_corporate_ltd_llc_name.txt
cat $1 | awk 'length($0) == 126' > $2/7_merger.txt
cat $1 | awk 'length($0) == 335' > $2/8_corporate_ltd_llc_reserved_registered_name.txt
cat $1 | awk 'length($0) == 508' > $2/9_ltd_compant.txt