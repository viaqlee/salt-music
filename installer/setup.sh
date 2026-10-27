#!/usr/bin/env bash
# Salt Music @VERSION@ — self-extracting installer.
# The program itself is a tar.gz glued to the end of this file, after the __PAYLOAD__ line.
#
#   ./SaltMusic-Setup.run                 wizard
#   ./SaltMusic-Setup.run --unattended    install with the defaults, no questions
#   ./SaltMusic-Setup.run --prefix DIR    install folder
#   ./SaltMusic-Setup.run --uninstall     remove an installed copy
#   ./SaltMusic-Setup.run --extract DIR   only unpack the files

set -u

VERSION="@VERSION@"
APP="Salt Music"
SELF="$(readlink -f "$0")"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/salt-music/app"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
BACKTITLE="$APP $VERSION Setup"
UNATTENDED=0
MODE=install
EXTRACT_TO=""

while [ $# -gt 0 ]; do
    case "$1" in
        --unattended|-y) UNATTENDED=1 ;;
        --prefix) PREFIX="$2"; shift ;;
        --uninstall) MODE=uninstall ;;
        --extract) MODE=extract; EXTRACT_TO="$2"; shift ;;
        --in-terminal) ;;
        -h|--help) sed -n '2,10p' "$SELF" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------- terminal
# Double-clicked in a file manager: no terminal yet, open one and run there.
if [ ! -t 0 ] && [ $UNATTENDED -eq 0 ] && [ "$MODE" != extract ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    args=(--in-terminal)
    [ "$MODE" = uninstall ] && args+=(--uninstall)
    for term in konsole gnome-terminal xfce4-terminal kitty alacritty foot wezterm xterm; do
        command -v "$term" >/dev/null || continue
        case "$term" in
            gnome-terminal) exec "$term" -- bash "$SELF" "${args[@]}" ;;
            xfce4-terminal) exec "$term" -x bash "$SELF" "${args[@]}" ;;
            wezterm) exec "$term" start -- bash "$SELF" "${args[@]}" ;;
            *) exec "$term" -e bash "$SELF" "${args[@]}" ;;
        esac
    done
    command -v notify-send >/dev/null && notify-send "$APP" "Run the installer from a terminal: bash $SELF"
    exit 1
fi

# ---------------------------------------------------------------- dialogs
# dialog gives the classic blue screen; whiptail looks alike; plain prompts as a last resort.
if [ $UNATTENDED -eq 1 ]; then UI=none
elif command -v dialog >/dev/null; then UI=dialog
elif command -v whiptail >/dev/null; then UI=whiptail
else UI=plain
fi
W=70
DLG=(--backtitle "$BACKTITLE")
[ $UI = dialog ] && DLG+=(--cr-wrap --no-collapse)  # keep the logo and the tables as drawn

tilde() { echo "${1/#$HOME/\~}"; }

box_h() {  # text -> dialog height that fits it
    local n; n=$(printf '%b' "$1" | wc -l)
    n=$((n + 7)); [ $n -lt 9 ] && n=9; [ $n -gt 22 ] && n=22; echo $n
}

ui_msg() {  # title text
    case $UI in
        dialog|whiptail) $UI "${DLG[@]}" --title "$1" --msgbox "$2" "$(box_h "$2")" $W ;;
        plain) printf '\n== %s ==\n%b\n\n[Enter] ' "$1" "$2"; read -r _ ;;
        none) printf '%b\n' "$2" ;;
    esac
}

ui_yesno() {  # title text [yes-label no-label] -> 0 yes
    local yes="${3:-Yes}" no="${4:-No}"
    case $UI in
        dialog) dialog "${DLG[@]}" --title "$1" --yes-label "$yes" --no-label "$no" --yesno "$2" "$(box_h "$2")" $W ;;
        whiptail) whiptail "${DLG[@]}" --title "$1" --yes-button "$yes" --no-button "$no" --yesno "$2" "$(box_h "$2")" $W ;;
        plain) printf '\n== %s ==\n%b\n%s/%s [y/n] ' "$1" "$2" "$yes" "$no"; read -r a; [[ "$a" =~ ^[YyДд] ]] ;;
        none) return 0 ;;
    esac
}

ui_input() {  # title text default -> prints value
    case $UI in
        dialog|whiptail) $UI "${DLG[@]}" --title "$1" --inputbox "$2" 12 $W "$3" 3>&1 1>&2 2>&3 ;;
        plain) printf '\n== %s ==\n%b\n[%s] ' "$1" "$2" "$3" >&2; read -r a; echo "${a:-$3}" ;;
        none) echo "$3" ;;
    esac
}

ui_checklist() {  # title text tag label on/off ... -> prints chosen tags
    local title="$1" text="$2"; shift 2
    case $UI in
        dialog|whiptail)
            $UI "${DLG[@]}" --title "$title" --separate-output --checklist "$text" 12 $W 4 "$@" \
                3>&1 1>&2 2>&3 ;;
        plain)
            printf '\n== %s ==\n' "$title" >&2
            while [ $# -gt 0 ]; do
                local def=n; [ "$3" = on ] && def=y
                printf '%s? [%s] ' "$2" "$def" >&2; read -r a; a="${a:-$def}"
                [[ "$a" =~ ^[YyДд] ]] && echo "$1"
                shift 3
            done ;;
        none) while [ $# -gt 0 ]; do [ "$3" = on ] && echo "$1"; shift 3; done ;;
    esac
}

# progress: feed "percent|text" lines on stdin
ui_gauge() {
    case $UI in
        dialog|whiptail)
            while IFS='|' read -r pct text; do printf 'XXX\n%s\n%s\nXXX\n' "$pct" "$text"; done |
                $UI "${DLG[@]}" --title "Installing" --gauge "Please wait..." 9 $W 0 ;;
        *) while IFS='|' read -r pct text; do printf '[%3s%%] %s\n' "$pct" "$text"; done ;;
    esac
}

bye() { [ $UI = dialog ] || [ $UI = whiptail ] && clear; exit "${1:-0}"; }

# ---------------------------------------------------------------- payload
extract_payload() {  # dir
    local line
    line=$(awk '/^__PAYLOAD__$/ { print NR + 1; exit }' "$SELF")
    mkdir -p "$1" && tail -n +"$line" "$SELF" | tar -xzf - -C "$1"
}

if [ "$MODE" = extract ]; then
    extract_payload "$EXTRACT_TO" && echo "Unpacked to $EXTRACT_TO"
    exit
fi

# ---------------------------------------------------------------- uninstall
uninstall() {
    local dir="$1" manifest="$1/.install-manifest"
    if [ ! -f "$manifest" ]; then
        ui_msg "Uninstall" "$APP is not installed in\n$(tilde "$dir")"
        bye 1
    fi
    ui_yesno "Uninstall" "Remove $APP from\n$(tilde "$dir") ?\n\nYour music folder is never touched." "Remove" "Cancel" || bye 0
    local keep=0
    ui_yesno "Settings" "Keep settings, download history and artist genres?\n(~/.config/salt-music, ~/.local/share/salt-music)" "Keep" "Delete" && keep=1
    while IFS= read -r f; do rm -f -- "$f"; done < "$manifest"
    rm -rf -- "$dir"
    if [ $keep -eq 0 ]; then
        rm -rf -- "${XDG_CONFIG_HOME:-$HOME/.config}/salt-music" "${XDG_DATA_HOME:-$HOME/.local/share}/salt-music"
    else
        rmdir --ignore-fail-on-non-empty "$(dirname "$dir")" 2>/dev/null
    fi
    command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS_DIR" 2>/dev/null
    ui_msg "Uninstall" "$APP has been removed.\n\nThanks for listening!"
    bye 0
}

[ "$MODE" = uninstall ] && uninstall "$PREFIX"

# ---------------------------------------------------------------- wizard
LOGO='
     ____        _ _     __  __           _
    / ___|  __ _| | |_  |  \/  |_   _ ___(_) ___
    \___ \ / _` | | __| | |\/| | | | / __| |/ __|
     ___) | (_| | | |_  | |  | | |_| \__ \ | (__
    |____/ \__,_|_|\__| |_|  |_|\__,_|___/_|\___|
'

ui_msg "Welcome" "$LOGO\n  Welcome to the $APP $VERSION Setup Wizard.\n\n  Albums, EPs, singles and whole artists from YouTube Music,\n  with tags, covers, genres, a player and phone sync.\n\n  Nothing is installed system-wide: everything goes to your\n  home folder. Press OK to continue, Esc to quit." || bye 1

UPDATE=0
if [ -f "$PREFIX/.install-manifest" ]; then
    old=$(cat "$PREFIX/.version" 2>/dev/null || echo "?")
    if ui_yesno "Already installed" "$APP $old is installed in\n$(tilde "$PREFIX")\n\nUpdate it to $VERSION? Settings and history stay." "Update" "Other folder"; then
        UPDATE=1
    fi
fi

if [ $UPDATE -eq 0 ]; then
    PREFIX=$(ui_input "Destination folder" "Setup will install $APP into this folder:" "$PREFIX") || bye 1
    PREFIX="${PREFIX/#\~/$HOME}"
    [ -n "$PREFIX" ] || bye 1
    case "$PREFIX" in /*) ;; *) PREFIX="$PWD/$PREFIX" ;; esac
    if [ -e "$PREFIX" ] && [ -n "$(ls -A "$PREFIX" 2>/dev/null)" ] && [ ! -f "$PREFIX/.install-manifest" ]; then
        ui_msg "Destination folder" "$(tilde "$PREFIX")\nis not empty. Pick an empty or a new folder."
        bye 1
    fi
fi

DESKTOP_DIR=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
opts=(menu "Start menu shortcut" on cmd "'salt-music' command in ~/.local/bin" on)
[ -d "$DESKTOP_DIR" ] && [ "$DESKTOP_DIR" != "$HOME" ] && opts+=(desktop "Desktop shortcut" off)
CHOSEN=$(ui_checklist "Components" "Choose what to set up:" "${opts[@]}") || bye 1

# --- system tools
PY=""
for cand in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python; do
    if command -v "$cand" >/dev/null && "$cand" -c 'import sys, venv; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        PY=$(command -v "$cand"); break
    fi
done
if [ -z "$PY" ]; then
    ui_msg "Python is missing" "$APP needs Python 3.10 or newer.\n\n  sudo pacman -S python\n\nInstall it and run Setup again."
    bye 1
fi

report=$(printf '  %-9s %-32s OK' python "$("$PY" -c 'import platform; print(platform.python_version())')")"\n"
missing=()
for pair in "ffmpeg:ffmpeg:sound conversion (required)" "mpv:mpv:built-in player" "deno:deno:YouTube signatures (required)" \
            "adb:android-tools:sending to the phone" "zenity:zenity:folder picker"; do
    IFS=: read -r cmd pkg what <<< "$pair"
    if command -v "$cmd" >/dev/null; then
        report+=$(printf '  %-9s %-32s OK' "$cmd" "$what")"\n"
    else
        report+=$(printf '  %-9s %-32s MISSING' "$cmd" "$what")"\n"
        missing+=("$pkg")
    fi
done
if [ ${#missing[@]} -gt 0 ]; then
    if command -v pacman >/dev/null && [ $UNATTENDED -eq 0 ]; then
        if ui_yesno "System check" "$report\nInstall the missing packages now?\n\n  sudo pacman -S ${missing[*]}\n\n(you will be asked for your password)" "Install" "Skip"; then
            [ $UI = dialog ] || [ $UI = whiptail ] && clear
            sudo pacman -S --needed "${missing[@]}" || ui_msg "System check" "pacman failed. You can install them later:\n\n  sudo pacman -S ${missing[*]}"
        fi
    else
        ui_msg "System check" "$report\nInstall them later with your package manager:\n  ${missing[*]}"
    fi
else
    ui_msg "System check" "$report\nEverything is in place." || bye 1
fi

ui_yesno "Ready to install" "Setup is ready to install $APP $VERSION.\n\n  Folder:      $(tilde "$PREFIX")\n  Components:  $(echo $CHOSEN)\n\nDownloading the Python libraries takes a minute or two." "Install" "Cancel" || bye 1

# ---------------------------------------------------------------- install
LOG="$PREFIX/install.log"
STATUS=$(mktemp)

do_install() {
    set -o pipefail
    echo "5|Unpacking files..."
    mkdir -p "$PREFIX" || return 1
    # fresh program files, but keep the venv for a quick update
    find "$PREFIX" -mindepth 1 -maxdepth 1 ! -name .venv ! -name install.log -exec rm -rf {} + 2>/dev/null
    extract_payload "$PREFIX" || return 1
    : > "$LOG"

    if [ ! -x "$PREFIX/.venv/bin/python" ]; then
        echo "12|Creating the Python environment..."
        "$PY" -m venv "$PREFIX/.venv" >> "$LOG" 2>&1 || return 1
    fi

    echo "18|Downloading libraries (flet, yt-dlp, ytmusicapi...)"
    local n=0 pct
    "$PREFIX/.venv/bin/python" -m pip install --disable-pip-version-check -U -r "$PREFIX/requirements.txt" 2>&1 |
        tee -a "$LOG" | while IFS= read -r line; do
            case "$line" in
                Collecting*|"Requirement already"*)
                    n=$((n + 1)); pct=$((18 + n * 2)); [ $pct -gt 80 ] && pct=80
                    pkg="${line#Collecting }"; pkg="${pkg#Requirement already satisfied: }"
                    echo "$pct|Downloading libraries: ${pkg%% *}" ;;
                "Installing collected"*) echo "85|Installing libraries..." ;;
            esac
        done || return 1

    echo "92|Creating shortcuts..."
    local manifest="$PREFIX/.install-manifest"
    : > "$manifest"
    mkdir -p "$ICON_DIR"
    cp "$PREFIX/assets/icon.svg" "$ICON_DIR/salt-music.svg" && echo "$ICON_DIR/salt-music.svg" >> "$manifest"

    cat > "$PREFIX/salt-music" <<EOF
#!/bin/sh
cd "$PREFIX" && exec "$PREFIX/.venv/bin/python" main.py "\$@"
EOF
    chmod +x "$PREFIX/salt-music"
    cp "$SELF" "$PREFIX/uninstall.run" && chmod +x "$PREFIX/uninstall.run"

    if grep -qx cmd <<< "$CHOSEN"; then
        mkdir -p "$BIN_DIR"
        ln -sf "$PREFIX/salt-music" "$BIN_DIR/salt-music" && echo "$BIN_DIR/salt-music" >> "$manifest"
    fi
    local entry="[Desktop Entry]
Type=Application
Name=$APP
GenericName=Music downloader
Comment=Download music from YouTube Music with tags and covers
Exec="$PREFIX/salt-music"
Icon=salt-music
Terminal=false
Categories=AudioVideo;Audio;
Keywords=youtube;music;download;yt-dlp;"
    if grep -qx menu <<< "$CHOSEN"; then
        mkdir -p "$APPS_DIR"
        echo "$entry" > "$APPS_DIR/salt-music.desktop"
        cat > "$APPS_DIR/salt-music-uninstall.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Uninstall $APP
Exec=bash "$PREFIX/uninstall.run" --uninstall --prefix "$PREFIX"
Icon=salt-music
Terminal=true
Categories=AudioVideo;Audio;
EOF
        printf '%s\n' "$APPS_DIR/salt-music.desktop" "$APPS_DIR/salt-music-uninstall.desktop" >> "$manifest"
        command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS_DIR" 2>/dev/null
    fi
    if grep -qx desktop <<< "$CHOSEN"; then
        echo "$entry" > "$DESKTOP_DIR/salt-music.desktop"
        chmod +x "$DESKTOP_DIR/salt-music.desktop"
        command -v gio >/dev/null && gio set "$DESKTOP_DIR/salt-music.desktop" metadata::trusted true 2>/dev/null
        echo "$DESKTOP_DIR/salt-music.desktop" >> "$manifest"
    fi
    echo "$VERSION" > "$PREFIX/.version"
    echo "100|Done."
}

( do_install; echo $? > "$STATUS" ) | ui_gauge
rc=$(cat "$STATUS"); rm -f "$STATUS"
if [ "$rc" != 0 ]; then
    ui_msg "Setup failed" "Something went wrong. The details are in\n$(tilde "$LOG")\n\n$(tail -n 6 "$LOG" 2>/dev/null)"
    bye 1
fi

path_note=""
if grep -qx cmd <<< "$CHOSEN" && [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    path_note="\n\n  Note: $(tilde "$BIN_DIR") is not in your PATH yet."
fi
if ui_yesno "Setup complete" "$APP $VERSION has been installed.\n\n  Folder:    $(tilde "$PREFIX")\n  Start it:  menu → $APP, or 'salt-music'\n  Remove it: menu → Uninstall $APP$path_note\n\nLaunch $APP now?" "Launch" "Finish" && [ $UNATTENDED -eq 0 ]; then
    setsid "$PREFIX/salt-music" >/dev/null 2>&1 < /dev/null &
fi
bye 0
__PAYLOAD__
