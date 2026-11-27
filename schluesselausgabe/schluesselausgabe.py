#!/usr/bin/env python3
"""
Erzeugt Schlüssel-Ausgabebelege (eine Seite pro Mitarbeiter) als PDF.

Eingabe: Excel (.xlsx) oder CSV mit den Spalten
         "Name" (oder "Vorname" + "Nachname") und "Spindnummer",
         optional "Raum" (mit --einzeln landet dann jede PDF im Ordner ihres Raums).
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
# Platzhalter {firma} und {spind} werden automatisch ersetzt, falls verwendet.
# ---------------------------------------------------------------------------
TITEL = "Empfangsbestätigung Spindschlüssel"
TEXT = """
Hiermit bestätige ich den Erhalt von zwei Spindschlüsseln für die Kaue auf dem Betriebshof Hamme.
<br/><br/>
Weiterhin bestätige ich mit meiner Unterschrift, die Regelungsabrede Nr. 46 „Regelungsabrede zur Nutzung der Kaue auf dem Betriebshof Hamme der Stadtwerke Bochum Gruppe“ zur Kenntnis genommen zu haben.
<br/><br/>
Beschädigungen am Spind sowie ein möglicher Verlust eines Schlüssels sind dem Team Gebäudemanagement (N-GB) unverzüglich zu melden.
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
        i_raum = finde(kopf, "raum", "räum", "zimmer", ausser=("spind",))
        if i_spind is not None and (i_name is not None or i_nach is not None):
            break
    else:
        sys.exit("Keine Kopfzeile mit den Spalten 'Name' (oder 'Vorname'/'Nachname') "
                 f"und 'Spindnummer' gefunden. Erste Zeile: {zeilen[0]}")

    def zelle(z, i):
        return z[i] if i is not None and i < len(z) else ""

    def natuerlich(t):
        return [(0, int(x), "") if x.isdigit() else (1, 0, x.lower()) for x in re.split(r"(\d+)", t)]

    ergebnis = []
    for z in zeilen[zi + 1:]:
        vor, nach = zelle(z, i_vor), zelle(z, i_nach)
        if not vor and not nach:
            # Nur eine Namensspalte: "Mustermann, Max" oder "Max Mustermann" (letztes Wort = Nachname)
            voll = zelle(z, i_name).strip()
            if "," in voll:
                nach, vor = (t.strip() for t in voll.split(",", 1))
            elif voll:
                *v, nach = voll.split()
                vor = " ".join(v)
        name = " ".join(t for t in (vor, nach) if t)
        spind = zelle(z, i_spind)
        raum = zelle(z, i_raum)
        if spind.endswith(".0"):  # Excel liefert Zahlen manchmal als 101.0
            spind = spind[:-2]
        if raum.endswith(".0"):
            raum = raum[:-2]
        if name:
            ergebnis.append((name, spind, raum, vor, nach))
    ergebnis.sort(key=lambda m: (not m[2], natuerlich(m[2]), m[4].lower(), m[3].lower()))
    return ergebnis


LOGO = Path(__file__).resolve().parent / "logo.png"


def zeichne_seite(c: canvas.Canvas, name: str, spind: str, raum: str, firma: str, mit_raum: bool):
    breite, hoehe = A4
    rand = 2.5 * cm
    textbreite = breite - 2 * rand

    # Kopf: links Firma + Datum, rechts Logo (logo.png neben dem Script)
    if LOGO.exists():
        from reportlab.lib.utils import ImageReader
        bild = ImageReader(str(LOGO))
        bw, bh = bild.getSize()
        lb = 4.2 * cm
        c.drawImage(bild, breite - rand - lb, hoehe - 1.5 * cm - lb * bh / bw, lb, lb * bh / bw, mask="auto")
    c.setFont(SCHRIFT, 10)
    c.drawString(rand, hoehe - 1.95 * cm, firma)
    c.drawString(rand, hoehe - 2.45 * cm, date.today().strftime("%d.%m.%Y"))

    c.setFont(SCHRIFT_FETT, 18)
    c.drawString(rand, hoehe - 4.3 * cm, TITEL)
    c.setLineWidth(0.8)
    c.line(rand, hoehe - 4.6 * cm, breite - rand, hoehe - 4.6 * cm)

    # Fließtext
    stil = ParagraphStyle("text", fontName=SCHRIFT, fontSize=11, leading=16)
    absatz = Paragraph(" ".join(TEXT.format(firma=firma, spind=spind or "____").split()), stil)
    _, h = absatz.wrap(textbreite, hoehe)
    absatz.drawOn(c, rand, hoehe - 5.6 * cm - h)

    # Datenblock unten
    felder = [("Mitarbeiter/in:", name), ("Spindnummer:", spind)] + ([("Raum:", raum)] if mit_raum else [])
    y = 10.3 * cm
    for label, wert in felder:
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


ERSATZ = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
                        "ı": "i", "İ": "I", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O",
                        "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe"})


def sicher(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", text.translate(ERSATZ))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9-]+", "_", t).strip("_")


def ordnername(raum: str) -> str:
    """Wie in Schluesselausgabe.html: '1.23' -> 'Raum_1.23', 'Werkstatt' -> 'Werkstatt'."""
    r = ".".join(t for t in (sicher(x) for x in raum.split(".")) if t)
    if not r:
        return "Ohne_Raum"
    return f"Raum_{r}" if r[0].isdigit() else r


def dateiname(vor: str, nach: str, spind: str) -> str:
    """Gleiches Schema wie Schluesselausgabe.html, z. B. Weiss_Juergen_Spind_7"""
    name = "_".join(t for t in (sicher(nach), sicher(vor)) if t) or "Mitarbeiter"
    return name + (f"_Spind_{sicher(spind)}" if spind else "")


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
    mit_raum = any(m[2] for m in mitarbeiter)
    if not mitarbeiter:
        sys.exit("Keine Mitarbeiter in der Liste gefunden.")

    if a.einzeln:
        ordner = a.ausgabe if a.ausgabe.suffix.lower() != ".pdf" else a.ausgabe.with_suffix("")
        ordner.mkdir(parents=True, exist_ok=True)
        vergeben = set()
        for name, spind, raum, vor, nach in mitarbeiter:
            ziel = ordner / ordnername(raum) if mit_raum else ordner
            ziel.mkdir(exist_ok=True)
            basis = dateiname(vor, nach, spind)
            datei, n = basis, 2
            while datei.lower() in vergeben:
                datei, n = f"{basis}_{n}", n + 1
            vergeben.add(datei.lower())
            c = canvas.Canvas(str(ziel / (datei + ".pdf")), pagesize=A4)
            zeichne_seite(c, name, spind, raum, a.firma, mit_raum)
            c.save()
        print(f"{len(mitarbeiter)} PDFs erstellt in: {ordner}" + (" (Unterordner je Raum)" if mit_raum else ""))
    else:
        c = canvas.Canvas(str(a.ausgabe), pagesize=A4)
        c.setTitle(TITEL)
        for name, spind, raum, _, _ in mitarbeiter:
            zeichne_seite(c, name, spind, raum, a.firma, mit_raum)
        c.save()
        print(f"{len(mitarbeiter)} Seiten erstellt: {a.ausgabe}")


if __name__ == "__main__":
    main()
