# Pipeweaver – Wave-Link-Alternative für CachyOS / Arch Linux

Elgato Wave Link gibt es nur für Windows und macOS. [Pipeweaver](https://github.com/pipeweaver/pipeweaver)
ist ein Open-Source-Tool, das stark von Wave Link inspiriert ist und direkt auf PipeWire (Standard bei CachyOS) aufsetzt:

| Wave Link                         | Pipeweaver                                         |
|-----------------------------------|----------------------------------------------------|
| Virtuelle Kanäle (Game, Musik, Chat …) | Virtuelle Kanäle frei anlegbar, mit Farben    |
| Monitor-Mix / Stream-Mix          | Matrix-Mixing: getrennte Lautstärken pro Ausgang   |
| Apps per Drag auf Kanäle          | Anwendungs-Management in der UI                    |
| Mikrofon einbinden                | Physische Geräte (z. B. Wave:3, Wave XLR) zuweisen |

> Hinweis: Pipeweaver ist laut Entwickler noch in aktiver Entwicklung – Einstellungen können sich bei Updates zurücksetzen.

## Bauen & Installieren

```bash
sudo pacman -S --needed base-devel git rust npm clang
git clone -b claude/elgato-streamdeck-linux-build-y500y2 https://github.com/nG64/Instax6garmi-remote.git
cd Instax6garmi-remote/pipeweaver
makepkg -si
```

Alternativ fertig aus dem AUR: `paru -S pipeweaver`.

## Benutzen

1. **Pipeweaver** aus dem Anwendungsmenü starten (startet den Daemon + Qt-Oberfläche).
   Die UI ist auch im Browser erreichbar: <http://localhost:14565>
2. Mikrofon (z. B. Wave:3) als Quelle zuweisen, Kopfhörer als Monitor-Ausgang.
3. In **OBS** den Stream-Mix als Audio-Eingang (PipeWire-Quelle) wählen.
4. Autostart lässt sich in den Pipeweaver-Einstellungen aktivieren.

Steuerung per Terminal: `pipeweaver-client --help` – praktisch für Stream-Deck-Tasten in **OpenDeck**
(Starterpack → „Run Command“, z. B. zum Muten eines Kanals).

## Elgato-Mikrofon-Hinweise

- **Wave:1 / Wave:3** funktionieren unter Linux als normales USB-Audio-Gerät. Hardware-Einstellungen wie
  Clipguard oder LED-Farbe lassen sich ohne Wave Link nicht ändern (sie bleiben aber im Mikrofon gespeichert –
  einmal unter Windows/macOS setzen reicht).
- **Wave XLR** hat keinen offiziellen Linux-Support; es gibt eine
  [Community-Anleitung mit WirePlumber-Skript](https://jmansar.github.io/wavexlr-on-linux-cfg/).
- Für Rauschunterdrückung/EQ am Mikrofon: `easyeffects` (`sudo pacman -S easyeffects`).
