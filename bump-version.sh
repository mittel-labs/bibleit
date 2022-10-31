#!/bin/bash

# shellcheck disable=SC2155
# shellcheck disable=SC2086
# shellcheck disable=SC2046
# shellcheck disable=SC2005
# shellcheck disable=SC2119
# shellcheck disable=SC2120

function get-version() {
  echo $(grep -Eo "([0-9]+)\.([0-9]+)\.([0-9]+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+)?" pyproject.toml)
}

function bump() {
    local VERSION=$(get-version)
    local NEW_VERSION=$(echo $VERSION | awk -F. '{OFS=".";$NF = $NF + 1;} 1')
    echo "bumping $1: $VERSION -> $NEW_VERSION"
  	sed -i '' 's/version = ".*"/version = "'${NEW_VERSION}'"/' "$1"
}

bump src/bibleit/config.py
bump pyproject.toml
echo git commit -am "version $(get-version)" src/bibleit/config.py pyproject.toml
git tag v$(get-version)
git push