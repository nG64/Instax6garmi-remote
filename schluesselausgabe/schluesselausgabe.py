#!/usr/bin/env python3
"""
Erzeugt Schlüssel-Ausgabebelege (eine Seite pro Mitarbeiter) als PDF.

Eingabe: CSV (Trennzeichen ; oder ,) oder Excel (.xlsx) mit den Spalten
         "Name" und "Spindnummer" (Groß-/Kleinschreibung egal).

Aufruf:
    python3 schluesselausgabe.py mitarbeiter.csv
    python3 schluesselausgabe.py mitarbeiter.xlsx -o belege.pdf --firma "Muster GmbH"
    python3 schluesselausgabe.py mitarbeiter.csv --einzeln      # eine PDF je Mitarbeiter

Benötigt: pip install reportlab openpyxl
"""
import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------------------
# Text oben auf dem Dokument – hier nach Bedarf anpassen.
# {firma} und {spind} werden automatisch ersetzt.
# ---------------------------------------------------------------------------
TITEL = "Empfangsbestätigung Spindschlüssel"
TEXT = """
Hiermit bestätige ich, den Schlüssel für den mir zugewiesenen Spind
Nr. <b>{spind}</b> von der Firma {firma} erhalten zu haben.
<br/><br/>
Ich verpflichte mich, den Schlüssel sorgfältig aufzubewahren, ihn nicht an
Dritte weiterzugeben und keine Kopien anfertigen zu lassen. Ein Verlust des
Schlüssels ist unverzüglich zu melden. Bei Verlust oder Beschädigung können
die Kosten für Ersatz bzw. Austausch des Schlosses in Rechnung gestellt werden.
<br/><br/>
Bei Beendigung des Arbeitsverhältnisses oder auf Aufforderung ist der Schlüssel
umgehend zurückzugeben.
"""


def lies_mitarbeiter(pfad: Path):
    """Liest die Mitarbeiterliste und gibt [(name, spind), ...] zurück."""
    if pfad.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(pfad, read_only=True, data_only=True).active
        zeilen = [["" if c is None else str(c).strip() for c in r]
                  for r in ws.iter_rows(values_only=True)]
    else:
        roh = pfad.read_bytes()
        for enc in ("utf-8-sig", "cp1252"):  # Excel-CSV ist oft cp1252
            try:
                text = roh.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        trenner = ";" if text.splitlines()[0].count(";") >= text.splitlines()[0].count(",") else ","
        zeilen = [[c.strip() for c in r] for r in csv.reader(text.splitlines(), delimiter=trenner)]

    zeilen = [z for z in zeilen if any(z)]
    if not zeilen:
        sys.exit("Die Mitarbeiterliste ist leer.")

    kopf = [k.lower() for k in zeilen[0]]
    try:
        i_name = next(i for i, k in enumerate(kopf) if "name" in k)
        i_spind = next(i for i, k in enumerate(kopf) if "spind" in k)
    except StopIteration:
        sys.exit(f"Spalten 'Name' und 'Spindnummer' nicht gefunden. Gefunden: {zeilen[0]}")

    ergebnis = []
    for z in zeilen[1:]:
        name = z[i_name] if i_name < len(z) else ""
        spind = z[i_spind] if i_spind < len(z) else ""
        if spind.endswith(".0"):  # Excel liefert Zahlen manchmal als 101.0
            spind = spind[:-2]
        if name:
            ergebnis.append((name, spind))
    return ergebnis


def zeichne_seite(c: canvas.Canvas, name: str, spind: str, firma: str):
    breite, hoehe = A4
    rand = 2.5 * cm
    textbreite = breite - 2 * rand

    # Kopf
    c.setFont("Helvetica", 10)
    c.drawString(rand, hoehe - 2 * cm, firma)
    c.drawRightString(breite - rand, hoehe - 2 * cm, date.today().strftime("%d.%m.%Y"))

    c.setFont("Helvetica-Bold", 18)
    c.drawString(rand, hoehe - 4 * cm, TITEL)
    c.setLineWidth(0.8)
    c.line(rand, hoehe - 4.4 * cm, breite - rand, hoehe - 4.4 * cm)

    # Fließtext
    stil = ParagraphStyle("text", fontName="Helvetica", fontSize=11, leading=16)
    absatz = Paragraph(" ".join(TEXT.format(firma=firma, spind=spind or "____").split()), stil)
    _, h = absatz.wrap(textbreite, hoehe)
    absatz.drawOn(c, rand, hoehe - 5.5 * cm - h)

    # Datenblock unten
    y = 9.5 * cm
    c.setFont("Helvetica-Bold", 11)
    for label, wert in (("Mitarbeiter/in:", name), ("Spindnummer:", spind)):
        c.setFont("Helvetica-Bold", 11)
        c.drawString(rand, y, label)
        c.setFont("Helvetica", 12)
        c.drawString(rand + 4 * cm, y, wert)
        c.setLineWidth(0.4)
        c.line(rand + 4 * cm, y - 0.15 * cm, breite - rand, y - 0.15 * cm)
        y -= 1.2 * cm

    # Unterschriftsfelder
    y = 4.5 * cm
    feld = (textbreite - 1.5 * cm) / 2
    c.setLineWidth(0.8)
    c.line(rand, y, rand + feld, y)
    c.line(breite - rand - feld, y, breite - rand, y)
    c.setFont("Helvetica", 9)
    c.drawString(rand, y - 0.5 * cm, "Ort, Datum")
    c.drawString(breite - rand - feld, y - 0.5 * cm, f"Unterschrift {name}")

    c.showPage()


def dateiname(name: str, spind: str) -> str:
    sauber = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    return f"Schluessel_{spind}_{sauber}.pdf"


def main():
    p = argparse.ArgumentParser(description="Erzeugt Schlüssel-Ausgabebelege als PDF.")
    p.add_argument("liste", type=Path, help="CSV- oder XLSX-Datei mit Spalten Name, Spindnummer")
    p.add_argument("-o", "--ausgabe", type=Path, default=Path("Schluesselausgabe.pdf"),
                   help="Ziel-PDF (bzw. Ordner bei --einzeln)")
    p.add_argument("--firma", default="[Firmenname]", help="Name der Firma für Text und Kopfzeile")
    p.add_argument("--einzeln", action="store_true", help="Eine eigene PDF pro Mitarbeiter")
    a = p.parse_args()

    mitarbeiter = lies_mitarbeiter(a.liste)

    if a.einzeln:
        ordner = a.ausgabe if a.ausgabe.suffix.lower() != ".pdf" else a.ausgabe.with_suffix("")
        ordner.mkdir(parents=True, exist_ok=True)
        for name, spind in mitarbeiter:
            c = canvas.Canvas(str(ordner / dateiname(name, spind)), pagesize=A4)
            zeichne_seite(c, name, spind, a.firma)
            c.save()
        print(f"{len(mitarbeiter)} PDFs erstellt in: {ordner}")
    else:
        c = canvas.Canvas(str(a.ausgabe), pagesize=A4)
        c.setTitle(TITEL)
        for name, spind in mitarbeiter:
            zeichne_seite(c, name, spind, a.firma)
        c.save()
        print(f"{len(mitarbeiter)} Seiten erstellt: {a.ausgabe}")


if __name__ == "__main__":
    main()
