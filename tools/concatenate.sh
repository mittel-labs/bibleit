#!/bin/bash

set -e

if [ $# -ne 1 ]; then
  echo "Usage: $0 <dir>"
  exit 1
fi

dir=$1
base_dir=$(dirname "$dir")

touch "$base_dir/output.txt"

old_dir=$(pwd)
cd "$dir"

for f in $(ls *.txt | sort -t'_' -k1,1n | grep -v output); do
  echo "Processing $f"
  sed -i '/^$/d' "$f"
  cat "$f" >> "../output.txt"
done

cd "$old_dir"
