# OpenX6 NAS-Backup (Ersatz für „Insta360 Cloud Backup“)

Eine Zusatzkomponente für [OpenX6](https://github.com/OpenX6/OpenX6) auf der **Insta360 X6**.
Sie sichert alle Aufnahmen automatisch per **WebDAV** auf deine eigene NAS statt in die Insta360-Cloud.

> ⚠️ **Status: ungetestet auf echter Hardware.** Der Code ist offline mit Tests abgesichert.
> Einige Annahmen über die Kamera sind aber noch nicht verifiziert (siehe „Offene Punkte“).
> Custom-Firmware kann die Kamera unbrauchbar machen. Lies vorher die Warnungen im OpenX6-README.

## Warum kein direkter Umbau von „Cloud Backup“?

Die originale Cloud-Backup-Funktion steckt in Insta360s geschlossenen Programmen (`ins_*`-Dienste und App).
OpenX6 enthält dafür keinen Quellcode. Um nur die Zieladresse umzubiegen, müsste man diese Binärdateien
reverse-engineeren und patchen. Das ist aufwendig und bei jedem Firmware-Update neu nötig.

Stattdessen läuft hier ein **eigener Dienst** auf der Kamera. Er übernimmt die Funktion vollständig und
ist offen und überprüfbar.

Die Python-Module aus dem OpenX6-SDK eignen sich dafür **nicht**. Sie laufen ohne Netzwerk
(eigener Netzwerk-Namespace) und dürfen höchstens 3 Sekunden laufen. Deshalb ist das hier eine
**Kernkomponente** wie `x6-wifi-idle.py`.

## Was der Dienst macht

| | |
|---|---|
| Quelle | `DCIM/` auf SD-Karte, internem Speicher und externer SSD (einstellbar) |
| Ziel | `<url>/<Seriennummer>/<sd\|internal\|ssd>/DCIM/<Ordner>/<Datei>` |
| Protokoll | WebDAV über HTTPS, auch mit selbst signiertem Zertifikat (`ca_file`) |
| Wann | alle `interval_seconds`, nur wenn die Kamera **nicht aufnimmt** und die NAS erreichbar ist |
| Sicherheit beim Upload | Upload als `.partial`, Größenprüfung auf der NAS, dann umbenennen. Startet eine Aufnahme, bricht der Upload innerhalb von etwa 5 Sekunden ab. |
| Nur fertige Dateien | Eine Datei wird erst hochgeladen, wenn sie sich über zwei Durchläufe nicht geändert hat und mindestens `settle_seconds` alt ist |
| Löschen | Standardmäßig **nie**. Optional mit `delete_after_upload: true` |
| Status | `/run/x6-nas-backup/status.json` (`idle`, `uploading`, `camera_busy`, `nas_unreachable`, `auth_failed`, `error`) |
| Rücksicht auf die Kamera | `Nice=10`, I/O-Klasse `idle` |

## 1. NAS vorbereiten

Beispiel **Synology**: Paket „WebDAV Server“ installieren, HTTPS aktivieren (Port 5006) und einen
freigegebenen Ordner `x6-backup` anlegen. Lege einen eigenen Benutzer `x6cam` an, der nur auf diesen
Ordner schreiben darf.

QNAP, TrueNAS, Nextcloud und ein Apache/nginx mit WebDAV funktionieren genauso.

Test vom PC aus:

```sh
curl -u x6cam -X PROPFIND -H "Depth: 0" https://192.168.1.20:5006/x6-backup/
```

## 2. In OpenX6 einbauen (eigener Fork)

```sh
git clone https://github.com/OpenX6/OpenX6
python3 -B integrate.py ./OpenX6
```

`integrate.py` kopiert den Dienst nach `components/assets/` und trägt ihn in `components/profile.json` ein.

**Wichtig:** OpenX6 prüft `components/profile.json` gegen eine Signatur
(`release/profile.sig`, `release/component-preview.pub`, `release/preview.json` mit
`profile_sha256` und Dateianzahl). Ohne neue Signatur bricht der Build mit
„Component profile mismatch“ ab. Für deinen Fork brauchst du also:

1. ein eigenes Schlüsselpaar für `component-preview.pub`,
2. eine neue Signatur von `profile.json` in `release/profile.sig`,
3. in `release/preview.json` den neuen `profile_sha256` (gibt `integrate.py` aus) und die neue Dateianzahl (`files`, +2).

Danach baust du mit der OpenX6-Desktop-App (aus deinem Fork gestartet) ein SD-Paket, wie im
OpenX6-README beschrieben, mit **deinem** Holder-Profil.

## 3. Konfigurieren

Kopiere `nas-backup.example.json` als **`nas-backup.json` ins Hauptverzeichnis der SD-Karte** und trage
URL, Benutzer und Passwort ein. Beim nächsten Start übernimmt der Dienst die Datei nach
`/data/x6-nas-backup/config.json` (Rechte 0600) und **löscht sie von der SD-Karte**, damit das Passwort
dort nicht liegen bleibt.

Bei einem selbst signierten NAS-Zertifikat: Zertifikat als PEM nach `/data/x6-nas-backup/nas.pem` legen
(per SSH/ADB) und `"ca_file": "/data/x6-nas-backup/nas.pem"` setzen. `verify_tls: false` funktioniert
auch, ist aber unsicher.

Prüfen per SSH auf der Kamera:

```sh
python3 -B /usr/local/sbin/x6-nas-backup.py --check
cat /run/x6-nas-backup/status.json
journalctl -u x6-nas-backup -f
```

## 4. Netzwerk: Kamera ins Heim-WLAN bringen

Die NAS muss von der Kamera aus erreichbar sein. Normalerweise spannt die X6 ein **eigenes** WLAN auf
(`wlan1`, 192.168.42.1). Die Kamera hat aber auch ein `wlan0`, das vermutlich für den Client-Modus der
originalen Cloud-Funktion gedacht ist.

- **Variante A (Ziel):** Die Kamera verbindet sich mit dem Heim-WLAN, z. B. über die WLAN-Einrichtung
  der originalen Cloud-Backup-Funktion. Ab dann sichert der Dienst von selbst, etwa beim Laden zu Hause.
- **Variante B (funktioniert sicher):** NAS oder PC verbinden sich mit dem Kamera-Hotspot und holen die
  Dateien selbst ab. Das ist ein anderes Modell und nicht Teil dieser Komponente.

## Entwickeln und testen

```sh
cd openx6-nas-backup
python3 -B -m unittest discover -s tests -v
```

Die Tests starten einen kleinen WebDAV-Server. Abgedeckt sind:

- Upload mit Prüfung
- keine erneuten Uploads nach einem Neustart
- Abbruch, wenn eine Aufnahme startet (keine halbe Datei unter dem endgültigen Namen)
- kein Netzwerkverkehr während der Aufnahme
- falsches Passwort
- `delete_after_upload`
- Übernahme der Konfiguration von der SD-Karte

Wenn du `src/x6-nas-backup.py` oder die Service-Datei änderst, erzeuge danach `profile-fragment.json`
neu, weil sich die SHA-256-Werte ändern. `integrate.py` bricht sonst ab.

## Offene Punkte (auf echter Hardware prüfen)

1. **WLAN-Client-Modus**: Kann `wlan0` dauerhaft mit dem Heim-WLAN verbunden werden, und über welche
   `ins_netd`-Methode? Das ist der wichtigste offene Punkt.
2. **Seriennummer**: Der Pfad wird geraten (`/ins/etc/serial`). Ersatzweise `"device_name": "MeineX6"` setzen.
3. **Aufnahmestatus**: Der Dienst nutzt dieselbe `ins_bll_cli share_state media`-Abfrage wie OpenX6s
   `storage-preflight.py`. Ob das auch für Intervall- und Zeitraffer-Aufnahmen „beschäftigt“ meldet, ist
   noch zu prüfen.
4. **Akku**: Uploads kosten Strom. Eventuell sollte der Dienst nur beim Laden laufen. Dafür fehlt noch
   die passende `kHald`-Abfrage.
5. **Ordnertiefe**: Bei großen Karten wird bei jedem Durchlauf ganz `DCIM/` eingelesen. Das ist mit
   einigen Tausend Dateien unkritisch, darüber hinaus wäre ein Index (`MISC/dcf_management.db`) besser.
