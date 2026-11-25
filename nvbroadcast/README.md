# NV Broadcast – NVIDIA-Broadcast-Alternative für CachyOS

Basiert auf [Hkshoonya/nvidia-broadcast-linux](https://github.com/Hkshoonya/nvidia-broadcast-linux)
(inoffiziell, GPL-3.0, von DocZeus). Funktionen u. a.:

- **Kamera:** Hintergrund-Unschärfe/-Ersatz, Green Screen, Auto-Frame, **Blickkorrektur (Eye Contact)**,
  Relighting, Hautglättung – als virtuelle Kamera für Discord, Zoom, OBS, Browser
- **Audio:** Mikrofon-Rauschentfernung, Lautsprecher-Entrauschen, Voice-Presets, VU-Meter
- **Optional:** lokale Meeting-Transkription (Whisper) und Zusammenfassung
- NVIDIA-GPU (CUDA, optional TensorRT) – oder CPU-Modi ohne NVIDIA

## Warum ein Skript statt PKGBUILD?

NV Broadcast ist eine Python-App, deren Installer eine eigene Laufzeitumgebung mit mehreren GB
CUDA-/ONNX-Paketen aus pip baut, vor dem Aktivieren testet und Updates/Rollbacks selbst verwaltet.
Das in ein pacman-Paket zu pressen würde genau diese Mechanik kaputt machen. `install-cachyos.sh`
übernimmt deshalb nur die **CachyOS-spezifische Vorbereitung** und ruft dann den Original-Installer auf:

1. Header-Pakete passend zu **jedem installierten Kernel** (`linux-cachyos`, `-lts`, `-bore` …) –
   der Original-Installer empfiehlt pauschal `linux-headers`, was auf CachyOS nicht passt
2. Systempakete (GTK4, Libadwaita, GStreamer, PipeWire, DKMS, v4l2loopback …)
3. Prüfung von NVIDIA-Treiber und Python-Version (unterstützt: 3.11–3.14)
4. Bau des v4l2loopback-Moduls (virtuelle Kamera)
5. Quellcode nach `~/.local/src/nvidia-broadcast-linux` holen (Standard: Release `v1.5.4`)
6. Original-`install.sh` starten

## Installation

```bash
cd Instax6garmi-remote && git pull
./nvbroadcast/install-cachyos.sh
```

Varianten:

```bash
./nvbroadcast/install-cachyos.sh --ref main                 # neuester Entwicklungsstand
./nvbroadcast/install-cachyos.sh -- --runtime cpu           # ohne NVIDIA-GPU
./nvbroadcast/install-cachyos.sh -- --with-meeting          # inkl. Whisper-Transkription
```

Der Original-Installer fragt unterwegs, ob CuPy (schnelle GPU-Compositing-Modi) und TensorRT
(Zeus/Killer-Modus, ~4,3 GB Download) installiert werden sollen.

## Danach

- „NV Broadcast“ aus dem Anwendungsmenü starten
- In Discord/Zoom/OBS die Kamera **„NVbroadcast“** wählen, als Mikrofon das virtuelle NV-Broadcast-Mikrofon
- Fehlt die Kamera: neu starten (falls gerade ein Kernel-Update lief) und `lsmod | grep v4l2loopback` prüfen

## Zusammenspiel mit Pipeweaver

Das entrauschte NV-Broadcast-Mikrofon in Pipeweaver als Mikrofon-Quelle zuweisen – dann läuft die
Rauschentfernung vor dem Monitor-/Stream-Mix.
