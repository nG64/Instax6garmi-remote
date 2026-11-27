#!/usr/bin/env python3
"""
Baut ../Schluesselausgabe.html aus vorlage.html: Bibliotheken und Schrift werden
eingebettet, damit die Datei ohne Internet und ohne Installation läuft.

Benötigt: npm (für den Download der Bibliotheken) und die Schrift Liberation Sans
(Linux: Paket fonts-liberation; oder Pfade unten anpassen).

    python3 build.py
"""
import base64
import subprocess
import tarfile
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ZIEL = HIER.parent / "Schluesselausgabe.html"
PAKETE = {
    "__XLSX__": ("xlsx@0.18.5", "package/dist/xlsx.full.min.js"),
    "__JSPDF__": ("jspdf@2.5.2", "package/dist/jspdf.umd.min.js"),
    "__JSZIP__": ("jszip@3.10.1", "package/dist/jszip.min.js"),
}
SCHRIFTEN = {
    "__FONT_REGULAR__": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "__FONT_BOLD__": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
}


def main():
    html = (HIER / "vorlage.html").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        for platzhalter, (paket, pfad) in PAKETE.items():
            tgz = subprocess.run(["npm", "pack", paket, "--silent"], cwd=tmp, check=True,
                                 capture_output=True, text=True).stdout.strip().splitlines()[-1]
            with tarfile.open(Path(tmp) / tgz) as t:
                js = t.extractfile(pfad).read().decode("utf-8")
            assert "</script" not in js.lower()
            html = html.replace(f"/*{platzhalter}*/", js, 1)
    for platzhalter, pfad in SCHRIFTEN.items():
        html = html.replace(f"/*{platzhalter}*/", base64.b64encode(Path(pfad).read_bytes()).decode(), 1)
    ZIEL.write_text(html, encoding="utf-8")
    print(f"Geschrieben: {ZIEL} ({ZIEL.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
