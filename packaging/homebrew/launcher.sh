#!/bin/bash
# The `openticker` command that Homebrew installs.
#
# OpenTicker lives in ~/.openticker as a git checkout, so that `openticker update` keeps your own changes and
# your coding agent can edit it. This launcher sets that up on first run with the same installer as the
# one-line install, then hands every command to the real CLI there. `brew upgrade` only updates this file.
set -euo pipefail

DIR="${OPENTICKER_DIR:-$HOME/.openticker}"
INSTALLER="@@LIBEXEC@@/install.sh"

if [ ! -x "$DIR/bin/openticker" ] || [ ! -x "$DIR/.venv/bin/python" ]; then
  if [ "${1:-}" = "setup" ]; then
    shift
    OPENTICKER_FROM_BREW=1 exec bash "$INSTALLER" "$@"
  fi
  OPENTICKER_FROM_BREW=1 bash "$INSTALLER"
  # setup already started OpenTicker and opened it; run whatever else was asked for
  [ "$#" -gt 0 ] || exit 0
fi

exec "$DIR/bin/openticker" "$@"
