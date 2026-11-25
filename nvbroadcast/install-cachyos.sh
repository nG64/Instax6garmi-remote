#!/usr/bin/env bash
# NV Broadcast (inoffizielle NVIDIA-Broadcast-Alternative) auf CachyOS / Arch installieren.
#
# Upstream: https://github.com/Hkshoonya/nvidia-broadcast-linux  (GPL-3.0, von DocZeus)
#
# Dieses Skript erledigt die CachyOS-spezifische Vorbereitung, die der Original-Installer
# nicht abdeckt (passende Kernel-Header für linux-cachyos*, DKMS, NVIDIA-Check, Python-Check),
# und startet danach den Original-Installer ./install.sh, der die Python-Umgebung baut.
#
# Aufruf:
#   ./install-cachyos.sh                 # stabiles Release (Standard-Tag unten)
#   ./install-cachyos.sh --ref main      # neuester Entwicklungsstand
#   ./install-cachyos.sh -- --runtime cpu --with-meeting   # Argumente nach "--" gehen an install.sh
set -euo pipefail

REPO_URL="https://github.com/Hkshoonya/nvidia-broadcast-linux.git"
REF="v1.5.4"
SRC_DIR="${NVB_SRC_DIR:-$HOME/.local/src/nvidia-broadcast-linux}"
UPSTREAM_ARGS=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --ref) REF="${2:?--ref braucht einen Tag/Branch}"; shift 2 ;;
        --dir) SRC_DIR="${2:?--dir braucht einen Pfad}"; shift 2 ;;
        --) shift; UPSTREAM_ARGS=("$@"); break ;;
        -h|--help) sed -n 2,15p "$0"; exit 0 ;;
        *) echo "Unbekanntes Argument: $1 (Upstream-Argumente nach '--' angeben)"; exit 2 ;;
    esac
done

info() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==> WARNUNG:\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m==> FEHLER:\033[0m %s\n' "$*"; exit 1; }

[ "$(id -u)" -ne 0 ] || die "Bitte NICHT als root starten – das Skript fragt selbst nach sudo."
command -v pacman >/dev/null || die "pacman nicht gefunden – dieses Skript ist für CachyOS/Arch."

# ─── 1. Kernel-Header passend zu ALLEN installierten Kerneln ──────────────────
# Der Original-Installer empfiehlt pauschal 'linux-headers'. Auf CachyOS heißt der Kernel aber
# z. B. linux-cachyos, linux-cachyos-lts, linux-cachyos-bore … – ohne die passenden Header baut
# DKMS das v4l2loopback-Modul nicht, und die virtuelle Kamera fehlt.
info "Ermittle installierte Kernel…"
HEADER_PKGS=()
for pkgbase_file in /usr/lib/modules/*/pkgbase; do
    [ -f "$pkgbase_file" ] || continue
    kpkg="$(<"$pkgbase_file")"
    if pacman -Si "${kpkg}-headers" &>/dev/null || pacman -Qi "${kpkg}-headers" &>/dev/null; then
        HEADER_PKGS+=("${kpkg}-headers")
        echo "    Kernel: $kpkg  →  ${kpkg}-headers"
    else
        warn "Kein Header-Paket '${kpkg}-headers' gefunden – v4l2loopback wird für $kpkg evtl. nicht gebaut."
    fi
done
[ "${#HEADER_PKGS[@]}" -gt 0 ] || warn "Keine Kernel-Header ermittelt. Ggf. manuell: sudo pacman -S linux-cachyos-headers"

# ─── 2. Systempakete ──────────────────────────────────────────────────────────
# Entspricht der Arch-Liste des Original-Installers, ergänzt um dkms, Header, pycairo
# und das GStreamer-PipeWire-Plugin.
SYS_PKGS=(
    git dkms v4l-utils v4l2loopback-dkms
    gtk4 libadwaita
    gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugin-pipewire
    python python-gobject python-cairo
    libayatana-appindicator psmisc libpulse pipewire
)
info "Installiere Systempakete (sudo)…"
sudo pacman -S --needed "${SYS_PKGS[@]}" "${HEADER_PKGS[@]}"

# ─── 3. NVIDIA-Treiber prüfen ─────────────────────────────────────────────────
if command -v nvidia-smi &>/dev/null && nvidia-smi -L &>/dev/null; then
    info "NVIDIA-GPU gefunden: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader | head -1)"
    info "CUDA-Bibliotheken bringt NV Broadcast selbst per pip mit – ein systemweites 'cuda'-Paket ist nicht nötig."
else
    warn "Kein funktionierender NVIDIA-Treiber (nvidia-smi) gefunden."
    warn "Auf CachyOS z. B. installieren mit:  sudo chwd -a   (oder: sudo pacman -S linux-cachyos-nvidia-open nvidia-utils)"
    warn "Ohne NVIDIA-GPU läuft NV Broadcast nur in den CPU-Modi (langsamer)."
fi

# ─── 4. Python-Version prüfen ─────────────────────────────────────────────────
PY_VER="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "$PY_VER" in
    3.11|3.12|3.13|3.14) info "System-Python $PY_VER wird unterstützt." ;;
    *) warn "System-Python $PY_VER liegt außerhalb des unterstützten Bereichs (3.11–3.14)."
       warn "Der Original-Installer bricht dann ab. Alternativen: Snap-Paket 'nvbroadcast' oder"
       warn "docs/PYTHON315.md im Upstream-Repo (experimentell, nur CPU)." ;;
esac
if ! python -c 'import gi; gi.require_version("Gtk","4.0"); gi.require_version("Adw","1"); gi.require_version("Gst","1.0"); from gi.repository import Gtk, Adw, Gst' 2>/dev/null; then
    die "GTK4/Libadwaita/GStreamer-Python-Bindings lassen sich nicht importieren – Paketinstallation prüfen."
fi

# ─── 5. DKMS-Modul bauen & laden ─────────────────────────────────────────────
info "Baue v4l2loopback für alle Kernel (dkms autoinstall)…"
sudo dkms autoinstall || warn "dkms autoinstall meldete Fehler – Ausgabe oben prüfen."
if ! modinfo v4l2loopback &>/dev/null; then
    warn "v4l2loopback-Modul für den laufenden Kernel ($(uname -r)) nicht verfügbar."
    warn "Häufigste Ursache: Kernel wurde aktualisiert, aber noch nicht neu gestartet → neu starten und Skript erneut ausführen."
fi

# ─── 6. Quellcode holen ──────────────────────────────────────────────────────
info "Hole NV Broadcast ($REF) nach $SRC_DIR…"
if [ -d "$SRC_DIR/.git" ]; then
    git -C "$SRC_DIR" fetch --tags --force origin
    git -C "$SRC_DIR" fetch origin "$REF" 2>/dev/null || true
    if git -C "$SRC_DIR" rev-parse -q --verify "refs/tags/$REF" >/dev/null; then
        git -C "$SRC_DIR" checkout -q "refs/tags/$REF"
    else
        git -C "$SRC_DIR" checkout -q -B "$REF" "origin/$REF"
    fi
else
    mkdir -p "$(dirname "$SRC_DIR")"
    git clone --branch "$REF" "$REPO_URL" "$SRC_DIR"
fi

# ─── 7. Original-Installer starten ───────────────────────────────────────────
info "Starte Original-Installer (fragt ggf. nach CuPy/TensorRT)…"
cd "$SRC_DIR"
./install.sh "${UPSTREAM_ARGS[@]}"

cat <<'EOF'

==> Fertig!
    Starten:     „NV Broadcast“ im Anwendungsmenü oder  ~/.local/bin/nvbroadcast
    Kamera:      In Discord/Zoom/OBS/Browser die Kamera „NVbroadcast“ (/dev/video10) wählen
    Mikrofon:    Das virtuelle, entrauschte Mikrofon von NV Broadcast als Eingang wählen
    Update:      dieses Skript erneut ausführen (ggf. mit --ref <neuer Tag>)
    Entfernen:   ~/.local/src/nvidia-broadcast-linux/uninstall.sh

    Tipp: Nach einem Kernel-Update baut DKMS v4l2loopback automatisch neu,
          solange die passenden *-headers installiert sind.
EOF
