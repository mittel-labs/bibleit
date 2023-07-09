#!/bin/bash

if [ $# -ne 1 ]; then
  echo "Usage: $0 <dir>"
  exit 1
fi

dir=$1
base_dir=$(dirname "$dir")

touch "$base_dir/output.txt"

for f in $(find "$dir" -type f | sort -t'_' -k1,1n | grep -v output); do
  echo "Processing $f"
#  sed -i '/^$/d' "$f"
#  cat "$f" >> "$base_dir/output.txt"
done
