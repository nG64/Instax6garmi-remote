#!/usr/bin/env python3
"""
Erzeugt Schlüssel-Ausgabebelege (eine Seite pro Mitarbeiter) als PDF.

Eingabe: Excel (.xlsx) oder CSV mit den Spalten
         "Name" (oder "Vorname" + "Nachname") und "Spindnummer".
         Groß-/Kleinschreibung egal, weitere Spalten werden ignoriert,
         die Kopfzeile darf auch weiter unten stehen (z. B. unter einem Titel).
         Vorlage: Mitarbeiterliste_Vorlage.xlsx

Aufruf:
    python3 schluesselausgabe.py mitarbeiter.csv
    python3 schluesselausgabe.py mitarbeiter.xlsx -o belege.pdf --firma "Muster GmbH"
    python3 schluesselausgabe.py mitarbeiter.xlsx --blatt "Tabelle2"
    python3 schluesselausgabe.py mitarbeiter.xlsx --einzeln     # eine PDF je Mitarbeiter

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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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


# Schrift mit vollem Zeichensatz einbinden, damit auch Namen wie "Ayşe Yılmaz"
# oder "Łukasz Wójcik" korrekt erscheinen. Gesucht wird in dieser Reihenfolge.
SCHRIFTEN = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
SCHRIFT, SCHRIFT_FETT = "Helvetica", "Helvetica-Bold"


def lade_schrift():
    global SCHRIFT, SCHRIFT_FETT
    for normal, fett in SCHRIFTEN:
        if Path(normal).exists() and Path(fett).exists():
            pdfmetrics.registerFont(TTFont("Text", normal))
            pdfmetrics.registerFont(TTFont("Text-Fett", fett))
            pdfmetrics.registerFontFamily("Text", normal="Text", bold="Text-Fett")
            SCHRIFT, SCHRIFT_FETT = "Text", "Text-Fett"
            return
    print("Hinweis: Keine Arial/DejaVu-Schrift gefunden – Sonderzeichen außerhalb "
          "von Deutsch/Westeuropa werden evtl. nicht korrekt dargestellt.", file=sys.stderr)


def lies_mitarbeiter(pfad: Path, blatt: str | None = None):
    """Liest die Mitarbeiterliste und gibt [(name, spind), ...] zurück."""
    if pfad.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(pfad, read_only=True, data_only=True)
        if blatt and blatt not in wb.sheetnames:
            sys.exit(f"Tabellenblatt '{blatt}' nicht gefunden. Vorhanden: {wb.sheetnames}")
        ws = wb[blatt] if blatt else wb.active
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

    # Kopfzeile suchen (muss nicht Zeile 1 sein, z. B. wenn oben ein Titel steht)
    def finde(kopf, *muster, ausser=()):
        for i, k in enumerate(kopf):
            if any(m in k for m in muster) and not any(a in k for a in ausser):
                return i
        return None

    for zi, z in enumerate(zeilen[:15]):
        kopf = [k.lower() for k in z]
        i_spind = finde(kopf, "spind", "schrank", "fach")
        i_vor = finde(kopf, "vorname")
        i_nach = finde(kopf, "nachname", "familienname")
        i_name = finde(kopf, "name", "mitarbeiter", ausser=("vor", "nach", "familien"))
        if i_spind is not None and (i_name is not None or i_nach is not None):
            break
    else:
        sys.exit("Keine Kopfzeile mit den Spalten 'Name' (oder 'Vorname'/'Nachname') "
                 f"und 'Spindnummer' gefunden. Erste Zeile: {zeilen[0]}")

    def zelle(z, i):
        return z[i] if i is not None and i < len(z) else ""

    ergebnis = []
    for z in zeilen[zi + 1:]:
        if i_vor is not None or i_nach is not None:
            name = " ".join(t for t in (zelle(z, i_vor), zelle(z, i_nach)) if t)
            if not name:
                name = zelle(z, i_name)
        else:
            name = zelle(z, i_name)
        spind = zelle(z, i_spind)
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
    c.setFont(SCHRIFT, 10)
    c.drawString(rand, hoehe - 2 * cm, firma)
    c.drawRightString(breite - rand, hoehe - 2 * cm, date.today().strftime("%d.%m.%Y"))

    c.setFont(SCHRIFT_FETT, 18)
    c.drawString(rand, hoehe - 4 * cm, TITEL)
    c.setLineWidth(0.8)
    c.line(rand, hoehe - 4.4 * cm, breite - rand, hoehe - 4.4 * cm)

    # Fließtext
    stil = ParagraphStyle("text", fontName=SCHRIFT, fontSize=11, leading=16)
    absatz = Paragraph(" ".join(TEXT.format(firma=firma, spind=spind or "____").split()), stil)
    _, h = absatz.wrap(textbreite, hoehe)
    absatz.drawOn(c, rand, hoehe - 5.5 * cm - h)

    # Datenblock unten
    y = 9.5 * cm
    c.setFont(SCHRIFT_FETT, 11)
    for label, wert in (("Mitarbeiter/in:", name), ("Spindnummer:", spind)):
        c.setFont(SCHRIFT_FETT, 11)
        c.drawString(rand, y, label)
        c.setFont(SCHRIFT, 12)
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
    c.setFont(SCHRIFT, 9)
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
    p.add_argument("--blatt", help="Name des Tabellenblatts (Standard: das aktive Blatt)")
    p.add_argument("--einzeln", action="store_true", help="Eine eigene PDF pro Mitarbeiter")
    a = p.parse_args()

    lade_schrift()
    mitarbeiter = lies_mitarbeiter(a.liste, a.blatt)
    if not mitarbeiter:
        sys.exit("Keine Mitarbeiter in der Liste gefunden.")

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
