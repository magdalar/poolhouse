#!/bin/sh
# Run yamllint and the Home Assistant blueprint tests in Docker.
# Extra arguments are passed to pytest, e.g.:
#   scripts/test.sh -k timeout
#   scripts/test.sh tests/test_handler.py::test_plain_toggle_turns_on_at_start
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
image=poolhouse-tests

docker build -q -t "$image" "$repo/tests" >/dev/null
docker run --rm --init -v "$repo:/repo:ro" -w /repo "$image" sh -c '
  set -e
  echo "== yamllint"
  yamllint -s .
  echo "== pytest"
  exec python -m pytest -p no:cacheprovider "$@"
' sh "$@"
