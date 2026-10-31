#!/usr/bin/env bash
# inputland installer: install, set up permissions and models, or uninstall.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${XDG_BIN_HOME:-$HOME/.local/bin}/inputland"
LAUNCHER_MARK="# managed by inputland install.sh"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/inputland"
RULE=/etc/udev/rules.d/99-inputland-uinput.rules
RULE_TEXT='KERNEL=="uinput", GROUP="uinput", MODE="0660", OPTIONS+="static_node=uinput"'
LOG="$(mktemp -t inputland-install.XXXXXX.log)"
ASSUME_YES=0
GUM=0
[[ -t 0 && -t 1 ]] && command -v gum >/dev/null && GUM=1

# --- UI -------------------------------------------------------------------

if [[ -t 1 ]]; then B=$'\e[1m' DIM=$'\e[2m' RED=$'\e[31m' GRN=$'\e[32m' YEL=$'\e[33m' R=$'\e[0m'; else B= DIM= RED= GRN= YEL= R=; fi

header() {
  if ((GUM)); then
    gum style --border rounded --padding "0 2" --margin "1 0" --bold "inputland" "$1"
  else
    printf '\n%s== inputland: %s ==%s\n\n' "$B" "$1" "$R"
  fi
}
step() { printf '%s::%s %s\n' "$B" "$R" "$*"; }
ok()   { printf '  %s✓%s %s\n' "$GRN" "$R" "$*"; }
warn() { printf '  %s!%s %s\n' "$YEL" "$R" "$*"; }
die()  { printf '  %s✗%s %s\n' "$RED" "$R" "$*" >&2; exit 1; }

confirm() {
  ((ASSUME_YES)) && return 0
  if ((GUM)); then gum confirm "$1"; return; fi
  [[ -t 0 ]] || die "No terminal to confirm \"$1\"; rerun with --yes."
  local a; read -rp "  $1 [y/N] " a; [[ $a == [yY]* ]]
}

# Run a command behind a spinner; on failure show its output.
run() {
  local title=$1; shift
  if ((GUM)); then
    gum spin --spinner dot --title "$title" -- bash -c '"$@" >>"$0" 2>&1' "$LOG" "$@" && return
  else
    printf '  %s%s...%s\n' "$DIM" "$title" "$R"
    "$@" >>"$LOG" 2>&1 && return
  fi
  tail -n 20 "$LOG" >&2
  die "$title failed (full log: $LOG)"
}

sudo_auth() { step "Administrator rights are needed for: $1"; sudo -v || die "sudo authentication failed."; }

# --- Steps ----------------------------------------------------------------

preflight() {
  [[ $(uname -s) == Linux ]] || die "inputland runs on Linux only."
  command -v uv >/dev/null || die "uv is not installed: 'sudo pacman -S uv', or see https://docs.astral.sh/uv/getting-started/installation/"
}

install_layer_shell() {
  step "HUD overlay library"
  if ldconfig -p | grep libgtk4-layer-shell >/dev/null; then ok "gtk4-layer-shell is installed"; return; fi
  if command -v pacman >/dev/null && confirm "Install gtk4-layer-shell with pacman?"; then
    sudo_auth "installing gtk4-layer-shell"
    run "Installing gtk4-layer-shell" sudo pacman -S --needed --noconfirm gtk4-layer-shell
    ok "gtk4-layer-shell installed"
  else
    warn "gtk4-layer-shell missing: install it from your distribution, or run with --no-hud"
  fi
}

install_env() {
  step "Python environment"
  run "Syncing dependencies (Python 3.13, MediaPipe, OpenCV)" uv sync --project "$ROOT" --locked
  ok "Environment ready in $ROOT/.venv"
}

install_launcher() {
  step "Launcher"
  if [[ -e $LAUNCHER ]] && ! grep -qF "$LAUNCHER_MARK" "$LAUNCHER"; then
    warn "$LAUNCHER exists and was not created by this script; left untouched"
    return
  fi
  mkdir -p "$(dirname "$LAUNCHER")"
  # Absolute uv path: keybindings and launchers often run with a minimal PATH.
  printf '#!/bin/sh\n%s\nexec "%s" run --project "%s" --locked inputland "$@"\n' \
    "$LAUNCHER_MARK" "$(command -v uv)" "$ROOT" >"$LAUNCHER"
  chmod 755 "$LAUNCHER"
  ok "Installed $LAUNCHER"
  [[ ":$PATH:" == *":$(dirname "$LAUNCHER"):"* ]] || warn "$(dirname "$LAUNCHER") is not in PATH; add it to run 'inputland' directly"
}

setup_uinput() {
  step "Virtual pointer permissions (/dev/uinput)"
  if [[ $(cat "$RULE" 2>/dev/null) == "$RULE_TEXT" ]] && id -nG | grep -qw uinput; then
    ok "Already configured"; return
  fi
  confirm "Create a 'uinput' group, a udev rule and add $USER to the group?" || { warn "Skipped: the cursor will not move without write access to /dev/uinput"; return; }
  sudo_auth "configuring /dev/uinput"
  run "Creating group 'uinput'" sudo groupadd -f uinput
  run "Writing $RULE" sudo bash -c 'printf "%s\n" "$1" >"$2"' _ "$RULE_TEXT" "$RULE"
  run "Adding $USER to 'uinput'" sudo usermod -aG uinput "$USER"
  run "Loading the uinput module" sudo modprobe uinput
  run "Applying the udev rule" sudo bash -c 'udevadm control --reload && udevadm trigger --name-match=uinput'
  ok "Permissions configured"
  id -nG | grep -qw uinput || warn "Log out and back in for the group membership to take effect"
}

setup_models() {
  step "Gesture and face models (~12 MB)"
  run "Downloading and verifying models" uv run --project "$ROOT" --locked python -c \
    'from inputland.tracking import *; ensure_model(MODEL_URL, MODEL_SHA256); ensure_model(FACE_MODEL_URL, FACE_MODEL_SHA256)'
  ok "Models cached in $CACHE"
}

check_camera() {
  step "Camera"
  if compgen -G '/dev/video*' >/dev/null; then ok "Found $(ls /dev/video* | tr '\n' ' ')"; else warn "No /dev/video* device found"; fi
}

# --- Commands -------------------------------------------------------------

cmd_setup() {
  setup_uinput
  setup_models
  check_camera
}

cmd_install() {
  header "Installation"
  preflight
  install_layer_shell
  install_env
  install_launcher
  cmd_setup
  header "Done"
  echo "  Start with:      inputland"
  echo "  Calibrate with:  inputland --preview"
}

cmd_setup_only() {
  header "Setup"
  preflight
  cmd_setup
  header "Done"
}

cmd_uninstall() {
  header "Uninstallation"
  confirm "Remove the launcher, the virtual environment and the cached models?" || die "Cancelled."
  step "Files"
  if [[ -e $LAUNCHER ]] && grep -qF "$LAUNCHER_MARK" "$LAUNCHER"; then rm -f "$LAUNCHER"; ok "Removed $LAUNCHER"; fi
  rm -rf "$CACHE" && ok "Removed $CACHE"
  rm -rf "$ROOT/.venv" && ok "Removed $ROOT/.venv"

  step "Virtual pointer permissions"
  if [[ -e $RULE ]] || id -nG "$USER" | grep -qw uinput; then
    if confirm "Remove the udev rule and $USER from the 'uinput' group? (other tools may rely on it)"; then
      sudo_auth "removing /dev/uinput permissions"
      [[ -e $RULE ]] && run "Removing $RULE" sudo rm -f "$RULE"
      id -nG "$USER" | grep -qw uinput && run "Removing $USER from 'uinput'" sudo gpasswd -d "$USER" uinput
      # Keep the group if another rule still grants it /dev/uinput.
      if getent group uinput >/dev/null && ! grep -qs 'GROUP="uinput"' /etc/udev/rules.d/*.rules; then
        run "Deleting group 'uinput'" sudo groupdel uinput
      fi
      run "Reloading udev rules" sudo udevadm control --reload
      ok "Permissions removed; reboot for it to take effect"
    else
      warn "Kept the uinput permissions"
    fi
  else
    ok "Nothing to remove"
  fi
  header "Done"
  echo "  The source in $ROOT was kept; delete it to remove inputland entirely."
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [command] [--yes]

Commands:
  install     Install dependencies and the 'inputland' command, then run setup
  setup       Configure /dev/uinput permissions and download the models
  uninstall   Remove what install and setup created
  (none)      Choose interactively

Options:
  -y, --yes   Answer yes to every question
EOF
}

main() {
  ((EUID)) || die "Run it as your user, not with sudo: it asks for sudo itself."
  local cmd=
  for a in "$@"; do
    case $a in
      -y|--yes) ASSUME_YES=1 ;;
      -h|--help) usage; exit 0 ;;
      install|setup|uninstall) cmd=$a ;;
      *) usage >&2; exit 2 ;;
    esac
  done
  if [[ -z $cmd ]]; then
    [[ -t 0 ]] || { usage >&2; exit 2; }
    header "Hand-gesture mouse control"
    local choice
    if ((GUM)); then
      choice=$(gum choose --header "Select an action" "Install" "Setup" "Uninstall" "Quit")
    else
      PS3="  Select an action: "
      select choice in Install Setup Uninstall Quit; do [[ -n $choice ]] && break; done
    fi
    cmd=${choice,,}
  fi
  case $cmd in
    install) cmd_install ;;
    setup) cmd_setup_only ;;
    uninstall) cmd_uninstall ;;
    *) exit 0 ;;
  esac
  rm -f "$LOG"
}

main "$@"
