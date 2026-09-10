#!/usr/bin/env bash
set -euo pipefail

cd -- "$BTT_WORKING_DIRECTORY"
paths=(check --)
while IFS= read -r path || [[ -n $path ]]; do
  path=${path%$'\r'}
  [[ -z $path ]] || paths+=("$path")
done <<< "$BTT_PATHS"

btt "${paths[@]}"
if [[ -n $BTT_TEST_COMMAND ]]; then
  bash --noprofile --norc -eo pipefail -c "$BTT_TEST_COMMAND"
fi
