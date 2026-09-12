#!/usr/bin/env bash
set -euo pipefail

report_script="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/report.py"
cd -- "$BTT_WORKING_DIRECTORY"
paths=(check --)
while IFS= read -r path || [[ -n $path ]]; do
  path=${path%$'\r'}
  [[ -z $path ]] || paths+=("$path")
done <<< "$BTT_PATHS"

log=$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/btt-check.XXXXXX")
trap 'rm -f -- "$log"' EXIT
status=0
btt "${paths[@]}" > "$log" 2>&1 || status=$?
stop_token=$(python3 -c 'import uuid; print(uuid.uuid4())')
printf '::stop-commands::%s\n' "$stop_token"
cat "$log"
printf '::%s::\n' "$stop_token"
report_status=0
python3 "$report_script" "$log" || report_status=$?
if (( status != 0 )); then
  exit "$status"
fi
if (( report_status != 0 )); then
  exit "$report_status"
fi
if [[ -n $BTT_TEST_COMMAND ]]; then
  bash --noprofile --norc -eo pipefail -c "$BTT_TEST_COMMAND"
fi
