# OpenDeck für CachyOS / Arch Linux

Elgato bietet **keine offizielle Stream-Deck-Software für Linux** an. [OpenDeck](https://github.com/nekename/OpenDeck)
ist der beste Ersatz: Es unterstützt alle Stream-Deck-Modelle (Original, Mini, XL, MK.2, +, Neo, Pedal …)
und kann **Plugins aus dem originalen Elgato-Stream-Deck-SDK** ausführen.

## Bauen & Installieren

```bash
sudo pacman -S --needed base-devel git rust deno
git clone -b claude/elgato-streamdeck-linux-build-y500y2 https://github.com/nG64/Instax6garmi-remote.git
cd Instax6garmi-remote/opendeck
makepkg -si
```

`makepkg -s` installiert die restlichen Abhängigkeiten (webkit2gtk-4.1, gtk3, libayatana-appindicator …) automatisch.
Der Build dauert je nach CPU ca. 5–10 Minuten.

## Nach der Installation

Die udev-Regeln landen in `/usr/lib/udev/rules.d/40-streamdeck.rules`. Einmal neu laden und den
Stream Deck **aus- und wieder einstecken**:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Danach `OpenDeck` aus dem Anwendungsmenü starten (oder `opendeck` im Terminal).

## Tipps

- Läuft noch die Flatpak-/AppImage-Version oder z. B. StreamController? Vorher beenden – nur ein Programm
  kann gleichzeitig auf den Stream Deck zugreifen.
- Windows-only-Plugins brauchen `wine`, Node.js-Plugins `nodejs` (optionale Abhängigkeiten).
- Neue Version: `pkgver` im `PKGBUILD` anpassen, `pkgrel=1` setzen, erneut `makepkg -si`.
- Alternative fertig gebaut: `paru -S opendeck-bin` (AUR) bzw. Flatpak `me.amankhanna.opendeck`.
