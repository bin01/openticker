#!/bin/bash
# OpenTicker installer.
#
#   curl -fsSL https://raw.githubusercontent.com/bin01/openticker/main/install.sh | bash
#
# Puts the code in ~/.openticker (or uses this checkout if you run it from one), creates a private Python
# environment with uv, links the `openticker` command into ~/.local/bin and runs `openticker setup`, which
# starts the background service, builds the Mac app and installs the agent skills. Your data lives in
# ~/Library/Application Support/OpenTicker and is never touched by updates.
#
# Options are passed to setup:  ... | bash -s -- --lan     let your phone connect over Wi-Fi
set -euo pipefail

REPO="https://github.com/bin01/openticker.git"
ORIG_PATH="$PATH"
DIR="${OPENTICKER_DIR:-$HOME/.openticker}"

bold=$'\033[1m'; dim=$'\033[2m'; green=$'\033[32m'; red=$'\033[31m'; reset=$'\033[0m'
[ -t 1 ] || { bold=""; dim=""; green=""; red=""; reset=""; }
step() { printf "  %s✓%s %s\n" "$green" "$reset" "$1"; }
fail() { printf "\n  %s✗%s %s\n\n" "$red" "$reset" "$1" >&2; exit 1; }

printf "\n%sInstalling OpenTicker%s\n\n" "$bold" "$reset"

case "$(uname -s)" in
  Darwin) MAC=1 ;;
  Linux)  MAC=0 ;;
  *) fail "OpenTicker runs on macOS (and Linux, without the Mac app)." ;;
esac

# Command line tools give us git and the Swift compiler for the app window.
if [ "$MAC" = 1 ] && ! xcode-select -p >/dev/null 2>&1; then
  xcode-select --install >/dev/null 2>&1 || true
  fail "macOS needs its Command Line Tools first. Finish the install window that just opened, then run this again."
fi
command -v git >/dev/null 2>&1 || fail "git is required."

# Use this checkout when the script is run from one; otherwise clone or update ~/.openticker.
HERE=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -n "$HERE" ] && [ -f "$HERE/app/server.py" ]; then
  DIR="$HERE"
  step "Using this copy at ${DIR/#$HOME/~}"
elif [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only -q || fail "Couldn't update $DIR (local changes?)."
  step "Updated ${DIR/#$HOME/~}"
else
  git clone -q --depth 1 "$REPO" "$DIR" || fail "Couldn't download OpenTicker from GitHub."
  step "Downloaded to ${DIR/#$HOME/~}"
fi

# uv manages Python for us, so the system Python (if any) doesn't matter.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || fail "Couldn't install uv (https://docs.astral.sh/uv)."
  export PATH="$HOME/.local/bin:$PATH"
  step "Installed uv"
fi
if [ ! -x "$DIR/.venv/bin/python" ]; then
  uv venv -q --python 3.12 "$DIR/.venv" || fail "Couldn't create the Python environment."
fi
uv pip install -q --python "$DIR/.venv/bin/python" -r "$DIR/requirements.txt" || fail "Couldn't install Python packages."
step "Python environment ready"

mkdir -p "$HOME/.local/bin"
chmod +x "$DIR/bin/openticker"
ln -sf "$DIR/bin/openticker" "$HOME/.local/bin/openticker"
step "Linked the openticker command into ~/.local/bin"

"$DIR/bin/openticker" setup "$@"

case ":$ORIG_PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) printf "\n  %sAdd ~/.local/bin to your PATH to use the openticker command:%s\n    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc\n" "$dim" "$reset" ;;
esac
