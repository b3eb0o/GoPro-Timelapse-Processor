# GoPro Time-Lapse Vibe-Coding Processor – Benutzeranleitung

**Version 2.4.1** · Stand 2026-10-12 · Entwicklungsstand: Beta

---

## 1. Einführung

### Was macht das Programm?

Das Programm macht aus den Zeitraffer-Dateien einer GoPro Hero 5 Black ein fertiges YouTube-Video. Du wählst eine Aufnahme aus, probierst per kurzer Vorschau aus, wie stark beschleunigt werden soll, und gibst Titel und Beschreibung ein (oder nimmst eine Vorlage). Danach rendert das Programm alle Teildateien („Chapter“) in einem Durchgang zu einem Video, prüft, ob nichts fehlt, lädt es auf YouTube hoch und verschiebt es ins Archiv. Bereits fertige Videos kannst du zusätzlich im Stapel hochladen.

### Für wen ist es gedacht?

- **Endanwender:** Du willst GoPro-Zeitraffer ohne Videoschnittprogramm veröffentlichen.
- **Power-User/Entwickler:** Du passt Encoder, Qualität, Ordner und YouTube-Einstellungen in der INI-Datei an oder entwickelst das Skript weiter.

### Was wird benötigt?

| Benötigt | Wofür |
|---|---|
| Windows-PC mit Python 3.8 oder neuer | Ausführen des Skripts |
| FFmpeg (mit ffprobe) | Rendern und Analysieren der Videos – **Pflicht** |
| VLC media player | Vorschau – optional |
| Google-Python-Pakete | YouTube-Upload |
| OAuth-Client-Datei (`client_secret.json`) für die YouTube Data API v3 | Anmeldung an deinem YouTube-Kanal |
| `gopro_config.ini` neben dem Skript | Alle Einstellungen |

---

## 2. Installation & Einrichtung

### 2.1 Systemvoraussetzungen

| Komponente | Anforderung |
|---|---|
| Betriebssystem | Windows 10/11 (primär). Linux/macOS grundsätzlich möglich, siehe FAQ |
| Python | ≥ 3.8 |
| Speicher | Ausreichend Platz in Ausgabe- und Archivordner für die fertigen Videos; Temp-Ordner für Testrender |
| RAM/CPU | Keine festen Vorgaben im Programm. Empfehlung: ≥ 8 GB RAM für 4K-Material; Grafikkarte mit Hardware-Encoder beschleunigt das Rendern deutlich |
| Internet | Für Upload und Erstanmeldung im Browser |

### 2.2 Installation Schritt für Schritt (PowerShell)

```bash
# 1) Python prüfen – erwartet wird 3.8 oder höher
python --version

# 2) YouTube-Pakete installieren
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2

# 3) FFmpeg installieren (https://ffmpeg.org/download.html) und prüfen,
#    ob beide Programme über PATH gefunden werden
ffmpeg -version
ffprobe -version

# 4) Optional: VLC installieren (Standardpfad C:\Program Files\VideoLAN\VLC\ wird automatisch gefunden)

# 5) Arbeitsordner anlegen und Dateien hineinkopieren.
#    WICHTIG: Die Konfiguration muss exakt "gopro_config.ini" heißen
#    (Datums-Präfix der ausgelieferten Datei entfernen).
mkdir C:\DATA\GoPro
Copy-Item .\2026-12-10_gopro_timelapse_processor.py C:\DATA\GoPro\gopro_timelapse_processor.py
Copy-Item .\2026-12-10_gopro_config.ini C:\DATA\GoPro\gopro_config.ini

# 6) Konfiguration öffnen und mindestens die beiden OAuth-Pfade anpassen
notepad C:\DATA\GoPro\gopro_config.ini
```

In Schritt 6 trägst du unter `[YouTube]` ein:

```ini
client_secrets_file = C:\DATA\GoPro\secrets\client_secret.json
token_file          = C:\DATA\GoPro\secrets\token.json
```

Die Token-Datei muss noch nicht existieren – sie entsteht bei der ersten Anmeldung.

### 2.3 Installation überprüfen

```bash
cd C:\DATA\GoPro

# Version anzeigen (prüft nur, dass Python das Skript starten kann)
python gopro_timelapse_processor.py --version
# Erwartet: GoPro Time-Lapse Processor 2.4.1 (2026-10-12)

# Trockenlauf im Uploadmodus (prüft INI, FFmpeg, Google-Pakete, Ordner)
python gopro_timelapse_processor.py -u --dry-run
```

Beim Trockenlauf werden fehlende Ordner (`aufnahmen`, `output`, `archiv`, `logs`, `temp`, `beschreibungen`) automatisch angelegt.

---

## 3. Schnellstart

### In 5 Schritten zum ersten Video

1. **Aufnahme kopieren:** Lege die MP4-Dateien einer Aufnahme in einen eigenen Unterordner, z. B. `C:\DATA\GoPro\aufnahmen\2026-09-25\`.
2. **Starten:** `python gopro_timelapse_processor.py`
3. **Aufnahme wählen und Vorschau ansehen:** Nummer eingeben; VLC zeigt kurz das Rohmaterial.
4. **Faktor testen:** Ziel-FPS bestätigen (Enter), Testrender-Dauer bestätigen (Enter), Faktor eingeben (z. B. `6`), Vorschau ansehen, mit `j` bestätigen.
5. **Titel eingeben und bestätigen:** Vorlage oder manuelle Eingabe, Zusammenfassung mit `j` bestätigen – Rendern, Upload und Archivierung laufen ohne weitere Eingabe.

### Konkretes Beispiel

Ausgangslage: Ordner `2026-09-25` mit 6 Dateien, Videomaterial 14min 56s, Faktor 6.

```
==============================================================================
Schritt 1/8  Aufnahme waehlen
==============================================================================
   Ermittle Aufnahmedaten in 2 Ordner(n)...
...
  1.  2026-09-25           2026-09-25 18:02  Zeitraum 12h 26min   Material    14min 56s    6 Dateien
Aufnahme waehlen (Nummer): 1
```

Ergebnis am Ende (gekürzt):

```
==============================================================================
✅ Verarbeitung abgeschlossen
==============================================================================
  Titel                           : 2026-09-25 - Sonnenuntergang
  YouTube                         : https://youtu.be/XXXXXXXXXXX

  Quellmaterial                   : 14min 56s  (6 Dateien)
  Ergebnis                        : 2min 29s
  Renderzeit                      : 7m 12s
  Uploadzeit                      : 3m 5s
  Archiviert                      : C:\DATA\GoPro\archiv\2026-09-25_final.mp4
==============================================================================
```

(Render- und Uploadzeiten sind Beispielwerte.)

---

## 4. Konfiguration

### 4.1 Wo werden Einstellungen geändert?

| Ort | Was |
|---|---|
| `gopro_config.ini` (neben dem Skript) | Alle dauerhaften Einstellungen |
| Kommandozeile | Betriebsmodus: `-u`/`--upload`, `--dry-run`/`--dryrun`/`-n`, `-h`/`--help`/`/?`/`-?`, `--version`/`-v` |
| Dialog während des Laufs | Ziel-FPS, Testrender-Dauer, Faktor, Titel, Beschreibung, Tags, Vorlage, Sichtbarkeit (Uploadmodus) |

Regeln für die INI: UTF-8 speichern, Werte ohne Anführungszeichen, Kommentare mit `;` oder `#`. Ja/Nein-Werte: `true/yes/ja/an/on/1` bzw. `false/no/nein/aus/off/0`. Ein `%` in Pfaden ist unkritisch (keine Interpolation).

### 4.2 Alle Parameter

| Parameter | Beschreibung | Typ | Standardwert | Beispiel |
|---|---|---|---|---|
| **[YouTube]** | | | | |
| `client_secrets_file` | Pfad zur OAuth-Client-Datei | Pfad | – (Pflicht) | `C:\DATA\GoPro\secrets\client_secret.json` |
| `token_file` | Speicherort des Anmelde-Tokens | Pfad | – (Pflicht) | `C:\DATA\GoPro\secrets\token.json` |
| `playlist_id` | Playlist für neue Videos; leer = keine | Text | leer | `PLxxxxxxxxxxxxxxxx` |
| `privacy_status` | Standard-Sichtbarkeit | `public`/`private`/`unlisted` | `private` | `unlisted` |
| `tags` | Standard-Tags, kommagetrennt | Liste | `Zeitraffer, GoPro` | `Zeitraffer, GoPro, Time-Lapse, 4K` |
| `category_id` | YouTube-Kategorie (nur Ziffern) | Zahl als Text | `19` | `28` |
| `public_stats_viewable` | Statistiken öffentlich | Ja/Nein | `true` | `false` |
| `embeddable` | Einbetten erlaubt | Ja/Nein | `true` | `true` |
| `license` | Lizenz (Groß-/Kleinschreibung beachten) | `youtube`/`creativeCommon` | `youtube` | `creativeCommon` |
| `made_for_kids` | Für Kinder bestimmt | Ja/Nein | `false` | `false` |
| `contains_synthetic_media` | Synthetische Inhalte | Ja/Nein | `false` | `false` |
| **[Verzeichnisse]** | | | | |
| `basis_dir` | Basisordner; leer = Skriptordner | Pfad | Skriptordner | `C:\DATA\GoPro` |
| `aufnahmen_dir` | Aufnahmen (ein Unterordner je Aufnahme) | Pfad | `<basis>\aufnahmen` | `D:\GoPro\Rohdaten` |
| `output_dir` | Gerenderte Videos | Pfad | `<basis>\output` | |
| `archiv_dir` | Hochgeladene Videos | Pfad | `<basis>\archiv` | |
| `log_dir` | Logdateien | Pfad | `<basis>\logs` | |
| `temp_dir` | Testrender | Pfad | `<basis>\temp` | |
| `beschreibung_dir` | Beschreibungs-Vorlagen (inkl. Unterordner) | Pfad | `<basis>\beschreibungen` | |
| **[Render]** | | | | |
| `encoder` | Video-Encoder | `auto`/`libx264`/`h264_nvenc`/`h264_qsv`/`h264_amf`/`h264_videotoolbox` | `auto` | `h264_nvenc` |
| `qualitaet` | Qualitätsstufe | `niedrig`/`mittel`/`hoch`/`maximal` | `hoch` | `maximal` |
| `tempo` | Encoder-Geschwindigkeit | `sehr schnell`/`schnell`/`ausgewogen`/`langsam` | `schnell` | `ausgewogen` |
| `ziel_fps` | Vorbelegung Ziel-Framerate; 0 = keine; **wird vom Skript aktualisiert** | Zahl 0–240 | `0` | `60` |
| `ziel_fps_merken` | Ziel-FPS nach erfolgreichem Lauf speichern | Ja/Nein | `true` | `false` |
| **[Ablauf]** | | | | |
| `testrender_dauer` | Vorschlag für die Testvorschau (s) | Zahl 1–300 | `20` | `30` |
| `erste_vorschau_dauer` | Länge der Rohmaterial-Vorschau (s) | Zahl 1–600 | `20` | `10` |
| `temp_auto_cleanup` | Derzeit ohne Wirkung (Temp wird immer aufgeräumt) | Ja/Nein | `true` | `true` |
| `archiv_versuche` | Versuche, wenn das Video gesperrt ist | Zahl 1–100 | `6` | `10` |
| `archiv_wartezeit` | Pause zwischen den Versuchen (s) | Zahl 0–600 | `10` | `15` |
| `materiallaenge_in_liste` | Spalte „Material“ in der Aufnahmeliste | Ja/Nein | `true` | `false` |
| **[Anzeige]** | | | | |
| `farben` | Farbige Konsole | Ja/Nein | `true` | `false` |
| `symbole` | Emojis statt `[OK]`, `[!]` … | Ja/Nein | `true` | `false` |
| `ausfuehrlich` | Jede Logzeile auch auf der Konsole | Ja/Nein | `false` | `true` |
| `breite` | Breite der Trennlinien | Zahl 40–200 | `78` | `100` |

> **Hinweis zur mitgelieferten neutralisierten INI:** Sie weicht bewusst von einigen Standardwerten ab: `tags = Zeitraffer, GoPro, Time-Lapse, 4K`, `license = creativeCommon`, `ziel_fps = 120`, `testrender_dauer = 5`, `erste_vorschau_dauer = 5`, `basis_dir = C:\DATA\GoPro`.

### 4.3 Empfohlene Einstellungen

| Anwendungsfall | Einstellungen |
|---|---|
| Schnell testen, kleine Dateien | `qualitaet = mittel`, `tempo = sehr schnell` |
| Archivqualität | `encoder = libx264`, `qualitaet = maximal`, `tempo = langsam` |
| NVIDIA-Grafikkarte erzwingen | `encoder = h264_nvenc` (wird beim Start geprüft, sonst `libx264`) |
| Veröffentlichung zunächst prüfen | `privacy_status = private` oder `unlisted` |
| Langsamer Ordnerscan bei vielen Aufnahmen | `materiallaenge_in_liste = false` blendet nur die Spalte aus; die Dauern werden trotzdem ermittelt, aber im Medienindex zwischengespeichert |
| Ohne Farben/Emojis (z. B. Umleitung in Datei) | `farben = false`, `symbole = false` |

---

## 5. Verwendung im Detail

### 5.1 Vollständiger Ablauf (ohne Optionen)

**Aufruf:** `python gopro_timelapse_processor.py`

| Schritt | Was passiert | Deine Eingabe |
|---|---|---|
| Vorab | Gerenderte Videos ohne Uploadmarker im Ausgabeordner werden als **offene Uploads** angeboten | `a` = alle, `1,3`, `2-5`, `n`/Enter = überspringen |
| 1/8 Aufnahme wählen | Liste aller Unterordner mit MP4, neueste zuerst | Nummer |
| – | Existiert `<Ordner>_final.mp4` schon ohne Marker → Rückfrage zum Überschreiben | `j`/`n` |
| 2/8 Umfang | Zeitraum (Wanduhr), Länge Videomaterial, Zeitraffer der Kamera | – |
| 3/8 Erste Vorschau | Erstes Chapter für `erste_vorschau_dauer` Sekunden in VLC | VLC schließen oder ablaufen lassen |
| 4/8 Einstellungen | Ziel-FPS (Enter = gespeicherter Wert, `?` = Empfehlungen), Testrender-Dauer | Zahl oder Enter |
| 5/8 Faktor testen | Vorschläge für Faktor 2/4/6/10, Testrender aus der größten LRV- (sonst MP4-)Datei, Wiedergabe | Faktor (z. B. `6` oder `2,5`), dann `j`/`n` |
| 6/8 Titel, Beschreibung, Tags | Vorlage wählen (`0` = manuell) oder manuell eingeben; Prüfung der YouTube-Limits | Text |
| Bestätigung | Auftragszusammenfassung (Material, Rendern, Veröffentlichung) | `j`/`n` |
| 7/8 Finalrender | Alle Chapter in einem Durchgang, Fortschrittsbalken, Vollständigkeitsprüfung | – |
| 8/8 YouTube-Upload | Upload mit Fortschritt, Playlist, Marker, Archivierung, Ziel-FPS speichern | – |

**Titelregel:** Steht am Anfang kein Datum, wird `YYYY-MM-DD - ` vorangestellt (Datum aus Ordnername → Metadaten `creation_time` → Dateidatum).

**Beschreibung:** Der Kopf wird immer automatisch erzeugt (englisch), danach folgt dein Text:

```
Recorded on 2026-09-25
GoPro Hero 5 Black, 4K time-lapse
Recording period: 12h 26min

Zeitraffer vom Balkon über den Abend.
```

Die Zeile `Recording period` entfällt, wenn die Aufnahmedauer nicht bestimmbar ist (z. B. nur eine Datei).

**Fortschrittsanzeige beim Rendern/Upload:**

```
   [████████████░░░░░░░░░░░░░░░░░░]  42%  3m 1s | noch ca. 4m 10s
```

### 5.2 Uploadmodus (`-u`)

**Aufruf:** `python gopro_timelapse_processor.py -u`

1. Alle MP4 aus Archiv (`A`) und Ausgabeordner (`O`) werden mit Größe, Datum und Uploadstatus angezeigt (`noch nicht hochgeladen` bzw. `hochgeladen x2: <ID>`).
2. Auswahl: `a`, `1,3`, `2-5`, `1,4-6`, `n`/Enter = abbrechen.
3. Bereits hochgeladene Videos → einmalige Rückfrage mit Links. Bei `n` werden nur die übrigen verarbeitet.
4. **Vorlage ist Pflicht** (eine für den ganzen Stapel).
5. Sichtbarkeit einmal wählen (`1`–`3`, Name oder Enter = Standard aus Vorlage bzw. INI).
6. Zusammenfassung bestätigen → Stapel läuft ohne weitere Eingaben.

Titel je Video: `<Datum> - <Vorlagentitel>`; ohne Vorlagentitel `<Datum> - Time-Lapse`. Videos aus dem Ausgabeordner werden nach dem Upload archiviert, Videos aus dem Archiv bleiben dort (nur der Marker wird ergänzt).

Bilanz am Ende:

```
  Erfolgreich       : 3
  Uebersprungen     : 1
  Fehlgeschlagen    : 0
  Gesamtdauer       : 12m 40s
```

### 5.3 Trockenlauf (`-u --dry-run`)

Zeigt Titel, Sichtbarkeit und die erste Beschreibungszeile je Video. Es wird **nichts hochgeladen, verschoben oder als Marker geschrieben**. Hinweis: Eine Logdatei, fehlende Ordner und ggf. der Medienindex `.gopro-media-index.json` werden dennoch angelegt. Ohne `-u` wird `--dry-run` ignoriert (mit Warnung).

### 5.4 Hilfe und Version

```bash
python gopro_timelapse_processor.py -h
python gopro_timelapse_processor.py --version
```

---

## 6. Eingabedaten

Das Programm verarbeitet **keine CSV-Dateien**. Eingaben sind Videodateien, Markdown-Vorlagen und die INI-Datei.

### 6.1 Videodateien

| Merkmal | Anforderung |
|---|---|
| Ablage | Je Aufnahme ein Unterordner in `aufnahmen_dir`; Ordnername idealerweise mit Datum `YYYY-MM-DD` am Anfang |
| Formate | `*.MP4`/`*.mp4` (Pflicht), `*.LRV` (optional, für schnelle Testrender) |
| Namensschema | `GOPR1290.MP4` = erstes Chapter, `GP011290.MP4`, `GP021290.MP4` … = Folgechapter (auch `GX`, `GH`, `GL`, `GO`) |
| Abweichende Namen | Sortierung nach Dateidatum mit Warnung – Reihenfolge prüfen |
| Auflösung | Einheitlich je Ordner empfohlen; abweichende Chapter werden auf die Auflösung der ersten Datei eingepasst (Warnung) |
| Zeitstempel | Für die Aufnahmedauer müssen die Änderungszeiten beim Kopieren erhalten bleiben |

Beispiel-Ordnerstruktur:

```
C:\DATA\GoPro\
├─ gopro_timelapse_processor.py
├─ gopro_config.ini
├─ aufnahmen\
│  └─ 2026-09-25\
│     ├─ GOPR1290.MP4
│     ├─ GOPR1290.LRV
│     ├─ GP011290.MP4
│     └─ GP021290.MP4
├─ beschreibungen\
│  └─ sonnenuntergang-beschreibung.md
├─ output\  archiv\  logs\  temp\
```

### 6.2 Beschreibungs-Vorlagen

Dateiname: `<name>-beschreibung.md` oder `<name>_beschreibung.md`, UTF-8, in `beschreibung_dir` (auch Unterordner). Abschnitte werden über Überschriften erster Ebene (`# …`) erkannt; `## …` gilt als normaler Text, HTML-Kommentare `<!-- -->` werden entfernt.

| Überschrift | Inhalt | Regel |
|---|---|---|
| `# Titel` / `# Title` | Titeltext | nur erste Zeile |
| `# Beschreibung` / `# Description` | Beschreibungstext | mehrzeilig |
| `# Tags` | Zusätzliche Tags | Liste (`- tag`) oder kommagetrennt |
| `# Aufnahmedatum` | Überschreibt das ermittelte Datum | nur `YYYY-MM-DD` |
| `# Sichtbarkeit` | Überschreibt die Sichtbarkeit | `public`/`private`/`unlisted` |

Beispiel (erste Zeilen einer gültigen Vorlage):

```markdown
# Titel
Sonnenuntergang
# Beschreibung
Zeitraffer vom Balkon über den Abend.
# Tags
```

### 6.3 Häufige Probleme mit Eingabedaten

| Problem | Lösung |
|---|---|
| Reihenfolge der Chapter falsch | Originalnamen der GoPro beibehalten |
| „Zeitraum unbekannt“ | Nur eine Datei oder identische Zeitstempel; beim Kopieren Zeitstempel erhalten (z. B. Explorer statt Werkzeuge, die das Änderungsdatum neu setzen) |
| Unplausibles Zeitraffer-Verhältnis (Log-Warnung) | Zeitstempel wurden verändert; es wird die ungekorrigierte Zeitspanne verwendet |
| Vorlagen-Datum ignoriert | Format `YYYY-MM-DD` verwenden, nicht `25.09.2026` |
| Vorlage nicht gefunden | Dateiname muss auf `-beschreibung.md` oder `_beschreibung.md` enden |
| `<` oder `>` im Text | Von YouTube nicht erlaubt – entfernen |

---

## 7. Ausgabedaten

| Datei | Ort | Format / Inhalt |
|---|---|---|
| `<Ordner>_final.mp4` | `output_dir`, nach Upload `archiv_dir` | H.264, `yuv420p`, gewählte FPS, **ohne Tonspur** |
| `<Ordner>_final.mp4.uploaded.json` | neben dem Video | Uploadmarker mit Historie |
| `<Ordner>_final_conflict_YYYYMMDD_HHMMSS.mp4` | `archiv_dir` | bei Namenskonflikt mit anderer Dateigröße |
| `.gopro-media-index.json` | in jedem Aufnahmeordner | zwischengespeicherte Dateidauern |
| `YYYYMMDD_HHMMSS.log` | `log_dir` | Protokoll des Laufs |
| `preview_<n>s.mp4` | `temp_dir` | Testrender, wird nach der Wiedergabe gelöscht |
| `gopro_config.ini.bak` | Skriptordner | Sicherung vor dem Speichern einer neuen Ziel-FPS |
| `token.json` | laut `token_file` | OAuth-Token (vertraulich behandeln) |

Beispiel Uploadmarker:

```json
{
  "youtube_video_id": "XXXXXXXXXXX",
  "source": "youtube_upload",
  "video_filename": "2026-09-25_final.mp4",
  "title": "2026-09-25 - Sonnenuntergang",
  "privacy_status": "private",
  "playlist_id": "",
  "uploaded_at_utc": "2026-09-26T08:15:02Z",
  "upload_count": 1,
  "uploads": [
    {
      "youtube_video_id": "XXXXXXXXXXX",
      "title": "2026-09-25 - Sonnenuntergang",
      "privacy_status": "private",
      "playlist_id": "",
      "uploaded_at_utc": "2026-09-26T08:15:02Z"
    }
  ]
}
```

Beispiel Medienindex (gekürzt):

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-12T17:05:11+02:00",
  "files": {
    "GOPR1290.MP4": { "size": 1234567, "mtime_ns": 1758812520000000000, "duration_seconds": 0.16 }
  },
  "summary": { "file_count": 6, "material_seconds": 896.0, "probe_failures": 0, "complete": true }
}
```

Die Datei darf gelöscht werden; sie wird beim nächsten Scan neu aufgebaut.

---

## 8. Fehlerbehebung (Troubleshooting)

| Fehlermeldung | Ursache | Lösung |
|---|---|---|
| `Keine Konfiguration gefunden!` | `gopro_config.ini` fehlt neben dem Skript (oder hat noch das Datums-Präfix) | Datei exakt `gopro_config.ini` nennen und neben das Skript legen |
| `gopro_config.ini ist nicht UTF-8-kodiert.` | Datei in ANSI gespeichert | Im Editor „Speichern unter“ → UTF-8 |
| `Eintrag 'client_secrets_file' fehlt im Abschnitt [YouTube] …` | Pflichteintrag fehlt | Eintrag ergänzen |
| `[YouTube] privacy_status = '…' ist ungueltig.` | Tippfehler | `public`, `private` oder `unlisted` |
| `[Ablauf] testrender_dauer = 301 ist groesser als 300.` | Wert außerhalb des Bereichs | Bereich laut Tabelle 4.2 einhalten |
| `ffmpeg und ffprobe wurde(n) nicht gefunden.` | FFmpeg nicht installiert / nicht im PATH | Installieren, PATH setzen, `ffmpeg -version` testen |
| `YouTube-API-Pakete fehlen: …` | Google-Pakete nicht installiert | `pip install google-api-python-client google-auth-oauthlib google-auth-httplib2` |
| `YouTube Client-Datei fehlt: …` | Pfad `client_secrets_file` falsch | Pfad korrigieren |
| `Aufnahmeverzeichnis existiert nicht: …` | `aufnahmen_dir` falsch | `[Verzeichnisse]` prüfen |
| `Keine Aufnahmen gefunden in: …` | Keine Unterordner mit MP4 | Aufnahme in einen **Unterordner** legen |
| `VLC nicht gefunden - Vorschauen werden uebersprungen.` | VLC fehlt | VLC installieren – Rendern/Upload funktionieren auch ohne |
| `Encoder '…' funktioniert auf diesem System nicht` | Treiber/Hardware fehlt oder FFmpeg ohne diesen Encoder | `encoder = auto` oder `libx264` |
| `Material reicht nur fuer …s statt …s` | Testrender-Datei zu kurz für Faktor × Dauer | Hinweis; Vorschau wird automatisch gekürzt |
| `Die Metadaten verletzen YouTube-Limits:` | Titel > 100, Beschreibung > 5000, Tags > 500 Zeichen oder `<`/`>` | Text kürzen, Skript neu starten (es wurde noch nichts gerendert) |
| `Das Ergebnis ist kuerzer als erwartet!` | Fertiges Video kürzer als Summe der Quelldauern / Faktor (Toleranz 2 %, mind. 1 s) | Video vor der Veröffentlichung prüfen (Upload läuft trotzdem!); Stream-Übersicht im Log; Quelldateien prüfen |
| `FFmpeg-Render fehlgeschlagen (Code …)` | FFmpeg-Fehler; letzte 8 Ausgabezeilen werden angezeigt | Meldung auswerten, ggf. `encoder = libx264` |
| `Upload fehlgeschlagen: …` | Netz, Quota oder ungültiges Token | Später erneut: beim nächsten Start „Offene Uploads“ oder `-u`; bei Token-Problemen `token.json` löschen und neu anmelden |
| `Archivierung fehlgeschlagen (Upload war erfolgreich).` | Video noch in einem Player geöffnet | Player schließen, Datei manuell verschieben; **nicht erneut hochladen** |
| `Uploadmarker konnte nicht geschrieben werden` | Schreibrechte | Video ist auf YouTube – beim nächsten Start nicht erneut hochladen |
| `Keine Beschreibungs-Vorlage gefunden.` (Uploadmodus) | Keine Vorlage in `beschreibung_dir` | Vorlage anlegen (siehe 6.2) |
| `Unbekannte Option: …` | Tippfehler in der Kommandozeile | `-h` für alle Optionen |

### Log-Dateien

- **Ort:** `log_dir` (Standard `<basis>\logs`), eine Datei je Lauf: `YYYYMMDD_HHMMSS.log`.
- **Format:** `2026-10-12 17:05:11 - WARNING - Abweichende Aufloesung GP021290.MP4: (1920, 1080)`
- **Interpretation:** `INFO` = Ablauf, `WARNING` = Auffälligkeit ohne Abbruch, `ERROR` = Fehler. Die Abschlussübersicht nennt die Anzahl der Warnungen und den Pfad der Logdatei. Mit `ausfuehrlich = true` erscheinen alle Logzeilen auch auf der Konsole.

---

## 9. FAQ

**Warum ist der „Zeitraum“ viel länger als das „Material“?**
Die Kamera rafft bereits beim Aufnehmen. „Zeitraum“ ist die echte Uhrzeit-Spanne der Aufnahme (z. B. 12h 26min), „Material“ die Länge der Videodateien (z. B. 14min 56s). In die YouTube-Beschreibung geht der Zeitraum.

**Welchen Faktor soll ich wählen?**
Das Programm zeigt dir in Schritt 5 die Ergebnislänge für die Faktoren 2, 4, 6 und 10. Der Faktor teilt die Materiallänge: 14min 56s bei Faktor 6 ergibt 2min 29s. Probiere mit dem Testrender, bis dir das Tempo gefällt – die Schleife läuft beliebig oft.

**Kann ich das Programm unbeaufsichtigt laufen lassen?**
Teilweise. Alle Eingaben finden vor der Bestätigung statt; danach laufen Render, Upload und Archivierung ohne Eingabe. Eine vollständig parameterbasierte Ausführung ohne Dialog gibt es nicht. Im Uploadmodus wird der gesamte Stapel nach einer Bestätigung abgearbeitet.

**Was passiert, wenn der Upload abbricht?**
Kurze Unterbrechungen werden bis zu 5-mal automatisch wiederholt. Scheitert der Upload endgültig, bleibt das Video im Ausgabeordner und wird beim nächsten Start als offener Upload angeboten – oder du nutzt `-u`.

**Was passiert, wenn ich das Rendern abbreche?**
Es bleibt eine unvollständige `<Ordner>_final.mp4` im Ausgabeordner. Sie wird beim nächsten Start als offener Upload angeboten – **nicht hochladen**, sondern löschen und neu rendern.

**Kann ich ein Video aus dem Archiv erneut hochladen?**
Ja, mit `-u`. Bereits hochgeladene Videos sind markiert; vor dem Upload kommt eine Warnung, da ein zweites YouTube-Video entsteht. Alle bisherigen YouTube-IDs bleiben im Uploadmarker erhalten. Die Zeile „Recording period“ fehlt, wenn der Aufnahmeordner nicht mehr existiert.

**Warum hat das fertige Video keinen Ton?**
Zeitraffer werden bewusst ohne Tonspur gerendert (`-an`), weil der Ton nicht mitbeschleunigt würde.

**Wie ändere ich die vorgeschlagene Ziel-FPS?**
Einfach im Dialog eine andere Zahl eingeben. Nach einem vollständig erfolgreichen Lauf wird sie in `gopro_config.ini` gespeichert (mit Sicherung `.bak`). Abschalten mit `ziel_fps_merken = false`.

**Funktioniert das Programm unter Linux oder macOS?**
Grundsätzlich ja (inkl. `h264_videotoolbox` auf macOS), primär ist es aber für Windows gebaut. Achtung: Dateien mit kleingeschriebener Endung `.mp4` werden auf diesen Systemen beim Finalrender nicht berücksichtigt – Endungen in `.MP4` belassen.

**Wie melde ich mich bei YouTube neu an?**
`token.json` (Pfad laut `token_file`) löschen. Beim nächsten Upload öffnet sich der Browser zur Anmeldung.

---

## 10. Technische Referenz

### 10.1 Klassen

| Klasse | Aufgabe |
|---|---|
| `UI` (Instanz `ui`) | Konsolenausgabe: `header`, `section`, `step`, `ok`, `warn`, `error`, `info`, `detail`, `kv`, `progress_bar`, `clear_line` |
| `Options` | Ausgewertete Kommandozeile (`upload_mode`, `dry_run`) |
| `ConfigError` | Ausnahme für Konfigurationsfehler |
| `Config` | INI laden (`text`, `flag`, `number`, `items`), `validate`, `save_ziel_fps` |
| `Logger` | Logdatei, `log`, `error_and_exit`, Sammlung von Warnungen/Fehlern |
| `FFmpegHandler` | Encoder-Erkennung (`_resolve_encoder`, `_auto_detect_encoder`, `_probe_encoder_works`, `_build_encoder_args`), `get_file_list`, `render_from_files`, `adjust_speed_with_progress`, `_run_with_progress`, `get_duration`, `get_video_size`, `get_creation_time`, `get_stream_summary` |
| `VLCPlayer` | VLC suchen und `play` (Fehler beenden nie das Programm) |
| `UploadMarker` | `marker_path`, `write_marker`, `read_marker`, `upload_count` |
| `ArchiveManager` | `archive_with_retry` |
| `BeschreibungTemplateManager` | `find_templates`, `parse` |
| `YouTubeUploader` | `get_service`, `build_tag_list`, `upload_video`, `add_to_playlist` |
| `MenuDialog` | Alle Dialoge, u. a. `show_recording_list`, `get_target_fps`, `get_test_preview_duration`, `get_speed_factor`, `get_job_details`, `confirm_job`, `show_pending_uploads`, `select_upload_candidates`, `confirm_reupload`, `select_batch_privacy`, `confirm_batch` |
| `GoProTimeLapseProcessor` | Orchestrierung: `list_recordings`, `estimate_span`, `get_total_source_duration`, `preview_first_clip`, `render_preview`, `render_final`, `upload_video`, `finalize_after_upload`, `find_pending_uploads`, `resume_pending_uploads`, `collect_upload_candidates`, `prepare_batch_entries`, `run_batch_upload` |

### 10.2 Funktionen auf Modulebene

| Funktion | Aufgabe |
|---|---|
| `main` | Einstieg: Argumente, Konfiguration, Werkzeugprüfung, Moduswahl |
| `parse_arguments` | Kommandozeile auswerten |
| `load_configuration` / `migrate_legacy_config` | INI laden bzw. aus `gopro_config.py` erzeugen |
| `ensure_external_tools` | ffmpeg/ffprobe im PATH prüfen |
| `run_full_mode` / `run_upload_mode` | Ablauf der beiden Modi |
| `parse_gopro_name` / `sort_gopro_files` | GoPro-Namensschema und Sortierung |
| `get_encoder_profile` | Encoder-Profil mit Fallback `libx264` |
| `validate_youtube_metadata` | YouTube-Limits prüfen |
| `build_description` | YouTube-Beschreibung mit englischem Kopf |
| `parse_selection` | Auswahl-Syntax `1,3`, `2-5`, `1,4-6` |
| `format_hms`, `format_h_min`, `format_span`, `format_material_len` | Zeitformatierung |
| `normalize_key` | Kleinschreibung, Umlaute → ae/oe/ue/ss, Leerzeichen/Bindestrich → `_` |
| `ask`, `ask_yes_no` | Eingaben mit sauberem Abbruch |
| `show_banner`, `show_config_summary`, `show_final_summary`, `show_batch_summary` | Start- und Abschlussausgaben |

### 10.3 Wichtige interne Datenstrukturen

| Struktur | Inhalt |
|---|---|
| `ENCODER_PROFILES` | je Encoder `label`, `speed_flag`, `speed`, `quality` (Übersetzung von `qualitaet`/`tempo`) |
| Aufnahme-Eintrag | `name`, `start`, `span_seconds`, `span_str`, `span_ratio`, `material_seconds`, `material_str`, `file_count` |
| Upload-Kandidat | `path`, `origin`, `origin_short`, `in_archive`, `size_mb`, `mtime`, `mtime_raw`, `marker` |
| Stapel-Bilanz | `erfolg`, `uebersprungen`, `fehler` |
| Konstanten | `YT_MAX_TITLE_LEN = 100`, `YT_MAX_DESCRIPTION_LEN = 5000`, `YT_MAX_TAGS_TOTAL_LEN = 500`, `SPAN_RATIO_MIN = 1.0`, `SPAN_RATIO_MAX = 500.0` |

### 10.4 Erweiterungsmöglichkeiten

- **Neuer Encoder:** Eintrag in `ENCODER_PROFILES` ergänzen (`speed_flag` = `None`, wenn der Encoder keine Stufen kennt).
- **Neuer Vorlagen-Abschnitt:** Überschrift in `BeschreibungTemplateManager.HEADER_MAP` aufnehmen und in `parse` auswerten.
- **Neuer INI-Wert:** in `Config._load_values` über `text`/`flag`/`number`/`items` einlesen, ggf. in `validate` prüfen und im `INI_TEMPLATE` (Migration) ergänzen.
- **Neue Kommandozeilenoption:** `Options`, `parse_arguments` und `HELP_TEXT` erweitern.
