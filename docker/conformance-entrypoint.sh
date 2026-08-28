#!/usr/bin/env bash
# Install sibling packs (mounted by compose) then run pytest.
#
# Core/playground mounts are :ro — copy them to /tmp before editable install
# (setuptools must write *.egg-info). This pack is mounted rw at /pack.
set -euo pipefail

export PIP_ROOT_USER_ACTION=ignore
export PIP_DISABLE_PIP_VERSION_CHECK=1

CORE="${RECQL_CORE_MOUNT:-/deps/core}"
PLAYGROUND="${RECQL_PLAYGROUND_MOUNT:-/deps/playground}"
PACK="${RECQL_PACK_MOUNT:-/pack}"

if [[ ! -f "$CORE/pyproject.toml" ]]; then
  echo "error: recql-python-core not mounted at $CORE" >&2
  echo "  Set RECQL_CORE_PATH to a checkout (default: ../recql-python-core)" >&2
  exit 1
fi
if [[ ! -f "$PACK/pyproject.toml" ]]; then
  echo "error: backend pack not mounted at $PACK" >&2
  exit 1
fi

python -m pip install -q -U pip setuptools wheel

STAGE=/tmp/recql-src
rm -rf "$STAGE"
mkdir -p "$STAGE/core"

copy_tree() {
  local src="$1" dst="$2"
  mkdir -p "$dst"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '.git' --exclude '.venv' --exclude '**/__pycache__' \
      --exclude '*.egg-info' --exclude '.pytest_cache' \
      "$src"/ "$dst"/
  else
    cp -a "$src"/. "$dst"/
    rm -rf "$dst"/*.egg-info 2>/dev/null || true
    find "$dst" -type d \( -name '__pycache__' -o -name '*.egg-info' \) -prune -exec rm -rf {} + 2>/dev/null || true
  fi
}

copy_tree "$CORE" "$STAGE/core"
# ranking: LightGBM for demo CTR seed used by scoring conformance tests
python -m pip install -q -e "${STAGE}/core[dev,conformance,ranking]" -e "${PACK}"

if [[ -f "$PLAYGROUND/pyproject.toml" ]]; then
  copy_tree "$PLAYGROUND" "$STAGE/playground"
  python -m pip install -q -e "${STAGE}/playground" --no-deps
else
  echo "warning: recql-playground not at $PLAYGROUND — integration seed may skip" >&2
fi

python -m pip install -q pytest pytest-asyncio

cd "$PACK"
exec python -m pytest "$@"
