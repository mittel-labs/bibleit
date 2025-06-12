#!/bin/bash

SED_BIN=${SED_BIN:-gsed}

set -e

if [ $# -ne 1 ]; then
  echo "Usage: $0 <dir>"
  exit 1
fi

## get name of directory
translation=$(basename "$1")

dir=$1
base_dir=$(realpath "$dir")
base_dir=$(dirname "$base_dir")

touch "$base_dir/${translation}"

bible_dir=$(realpath translations)

old_dir=$(pwd)
cd "$dir"

for f in $(ls *.txt | sort -t'_' -k1,1n | grep -v output); do
  echo "Processing $f"
  gsed -i '/^$/d' "$f"
  cat "$f" >> "${bible_dir}/${translation}"
done

cd "$old_dir"
