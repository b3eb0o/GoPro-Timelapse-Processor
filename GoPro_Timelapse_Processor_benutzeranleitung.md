# GoPro Time-Lapse Vibe-Coding Processor – Benutzeranleitung

**Version:** 2.0.23 | **Zielplattform:** Primär Windows, Python 3.8+

---

## 1. Einführung

Der GoPro Time-Lapse Vibe-Coding Processor erstellt aus einem GoPro-Aufnahmeordner automatisch ein beschleunigtes MP4-Zeitraffervideo. Vor dem vollständigen Rendern kannst du Geschwindigkeitsfaktor und Bildrate mit einem schnellen Testrender prüfen, der automatisch die größte verfügbare Vorschaudatei verwendet. Nach deiner Bestätigung rendert das Programm das gesamte Video, lädt es zu YouTube hoch, ordnet es einer Playlist zu und verschiebt die fertige Datei ins Archiv.

Es richtet sich an GoPro-Nutzer und Content-Creator, die regelmäßig Zeitraffer veröffentlichen und einen lokalen, menügeführten Windows-Workflow ohne manuelles Videoschnittprogramm bevorzugen.

Benötigt werden: Python, FFmpeg (inkl. ffprobe), VLC, ein YouTube-Konto mit aktivierter YouTube Data API v3 sowie GoPro-MP4-Dateien. Für den Upload sind eine Google-OAuth-Datei (`client_secret.json`) und die Konfigurationsdatei `gopro_config.py` erforderlich.

---

## 2. Installation & Einrichtung

### Systemvoraussetzungen

| Bereich | Voraussetzung |
|---|---|
| Betriebssystem | Windows 10/11 empfohlen; andere Systeme benötigen VLC im `PATH` |
| Python | 3.8 oder neuer |
| Video-Tools | FFmpeg und ffprobe im `PATH`; VLC installiert |
| Internet | Für OAuth-Anmeldung und YouTube-Upload |
| Google | Google-Cloud-Projekt mit aktivierter YouTube Data API v3 |

### Installation

```bash
# Schritt 1: Projektordner anlegen
mkdir GoProProcessor
cd GoProProcessor

# Schritt 2: gopro_timelapse_processor_v2.0.23.py und gopro_config.py
# in diesen Ordner kopieren (beide MUESSEN nebeneinander liegen)

# Schritt 3: Virtuelle Python-Umgebung anlegen (Windows)
py -3 -m venv .venv
.venv\Scripts\activate

# Schritt 4: Benoetigte Python-Pakete installieren
python -m pip install --upgrade pip
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2

# Schritt 5: FFmpeg und ffprobe pruefen
ffmpeg -version
ffprobe -version

# Schritt 6: VLC pruefen (alternativ am Windows-Standardpfad installieren)
vlc --version

# Schritt 7: Ordnerstruktur anlegen
mkdir aufnahmen output archiv logs temp beschreibungen
```

### Google/YouTube einrichten

- Google Cloud Console öffnen, Projekt erstellen/wählen.
- **YouTube Data API v3** aktivieren.
- OAuth-Anmeldedaten für eine **Desktop-App** erstellen.
- Client-Datei herunterladen, als `client_secret.json` an geschütztem Ort speichern.
- Pfad in `YOUTUBE_CLIENT_SECRETS_FILE` eintragen.
- Beim ersten Upload öffnet sich automatisch ein Browserfenster für die OAuth-Freigabe; danach wird die Token-Datei angelegt.

### Installation prüfen

```bash
python --version
pip show google-api-python-client google-auth-oauthlib google-auth-httplib2
python gopro_timelapse_processor_v2.0.23.py
```

Bei korrekter Einrichtung erscheinen zu Beginn die geladene Konfiguration, Playlist-ID, Sichtbarkeit, der Pfad zu den Beschreibungs-Vorlagen und der erkannte Video-Encoder. Fehlt `gopro_config.py`, meldet das Programm dies explizit und beendet sich.

---

## 3. Schnellstart

1. GoPro-Aufnahme in einen neuen Unterordner unter `aufnahmen/` kopieren.
2. Hauptskript starten.
3. Im Menü die Nummer der Aufnahme wählen.
4. Erste Clip-Vorschau ansehen, Ziel-FPS und Testrender-Dauer eingeben, dann Geschwindigkeitsfaktor testen (Testrender nutzt automatisch die größte LRV-/MP4-Datei).
5. Titel/Beschreibung/Tags eingeben (manuell oder aus Vorlage) und den Auftrag mit `j` bestätigen.

Beispielstruktur:
```
aufnahmen/
└── 2026-09-20_11-58/
    ├── GOPR0001.MP4
    ├── GP010001.MP4
    ├── GOPR0001.LRV
    └── GP010001.LRV
```

Beispielinteraktion:
```
📁 Verfügbare Aufnahmen (neu nach alt):
  1. 2026-09-20_11-58 | Start: 2026-09-20 11:58 | Dauer: 0h 15min
Auswahl (Nummer): 1
Ziel-FPS eingeben (Standard: 60): 60
Testrender-Dauer in Sekunden (Standard: 20): 20
Geschwindigkeitsfaktor (z.B. 2.0 für doppelte Geschwindigkeit): 7.0
Zufrieden mit der Vorschau? (j/n): j
```

Als Ergebnis entsteht nach Render und Upload z. B. `archiv/2026-09-20_11-58_final.mp4`. Die konkrete Renderzeit hängt von Quellmaterial, gewähltem Encoder und Rechnerleistung ab.

---

## 4. Konfiguration

Bearbeite ausschließlich `gopro_config.py`, die neben dem Hauptskript liegt.

| Parameter | Beschreibung | Typ | Standardwert | Beispiel |
|---|---|---|---|---|
| `YOUTUBE_CLIENT_SECRETS_FILE` | Pfad zur Google-OAuth-Clientdatei | `str` | – (Pflicht) | `r"C:\Secrets\client_secret.json"` |
| `YOUTUBE_TOKEN_FILE` | Pfad zur OAuth-Token-Datei | `str` | – (Pflicht) | `r"C:\DATA\Video\GoPro\YT\token.json"` |
| `YOUTUBE_PLAYLIST_ID` | Globale Ziel-Playlist | `str` | – (Pflicht) | `"PL..."` |
| `YOUTUBE_PRIVACY_STATUS` | Sichtbarkeit des Uploads | `str` | – (Pflicht) | `"private"` |
| `YOUTUBE_TAGS` | Standard-Tags für alle Uploads | `list[str]` | – (Pflicht) | `['Zeitraffer', 'GoPro']` |
| `YOUTUBE_CATEGORY_ID` | YouTube-Kategorie | `str` | – (Pflicht) | `"19"` |
| `BASE_DIR` / `OUTPUT_DIR` / `ARCHIVE_DIR` / `LOG_DIR` / `TEMP_DIR` | Verzeichnisse | `str` | leer = relativer Standardpfad | `r"D:\GoProOutput"` |
| `BESCHREIBUNG_DIR` | Zentralordner für Beschreibungs-Vorlagen | `str` | leer = `./beschreibungen` | `r"D:\Vorlagen"` |
| `FFMPEG_ENCODER` | Video-Encoder | `str` | `"auto"` | `"h264_nvenc"` |
| `FFMPEG_PRESET` | Encoder-Preset | `str` | `""` (Standard) | `"fast"` |

Empfehlungen:

| Situation | Einstellung |
|---|---|
| Erstes Testvideo | `YOUTUBE_PRIVACY_STATUS = "private"` |
| Schnelleres Rendern mit NVIDIA-GPU | `FFMPEG_ENCODER = "h264_nvenc"`, `FFMPEG_PRESET = "fast"` |
| Kein passender Encoder bekannt | `FFMPEG_ENCODER = "auto"` (automatische Erkennung beim Start) |

---

## 5. Verwendung im Detail

### Aufnahme auswählen
`list_recordings()` sucht in `./aufnahmen/` nach Unterordnern mit `*.MP4` und zeigt sie absteigend nach Startzeitpunkt.

### Erste Clip-Vorschau
`preview_first_clip()` spielt den zeitlich ältesten MP4-Clip 20 Sekunden über VLC ab.

### Ziel-FPS, Testrender-Dauer und Geschwindigkeitsfaktor
`get_target_fps()` akzeptiert 1–240 (Standard 60). `get_test_preview_duration()` akzeptiert 1–300 Sekunden (Standard 20). `get_speed_factor()` akzeptiert jede positive Dezimalzahl.

### Testrender
`render_preview()` verwendet **ausschließlich die größte** LRV-Datei im Aufnahmeordner (Fallback: größte MP4-Datei), um kurze, unvollständige "Fehlstart"-Clips als Testquelle zu vermeiden. Reicht die Dauer dieser Datei nicht für die gewünschte Testrender-Länge, wird automatisch verkürzt gerendert – mit deutlicher Warnung auf Konsole und im Log.

### Metadaten und Bestätigung
`get_job_details()` sucht zuerst im Zentralordner (`BESCHREIBUNG_DIR`) nach Vorlagen (siehe Abschnitt 6). Werden welche gefunden, erscheint immer ein Auswahlmenü inklusive Option "manuelle Eingabe". Fehlende Felder einer gewählten Vorlage werden interaktiv nachgefragt.

### Finalrender, Upload und Archivierung
`render_final()` concateniert **alle** MP4-Dateien und rendert in voller Auflösung. `YouTubeUploader.upload_video()` lädt hoch, zeigt vorher die finale Tag-Liste an. `add_to_playlist()` ordnet der globalen Playlist zu. Bei Erfolg schreibt `UploadMarker.write_marker()` den JSON-Marker, `ArchiveManager.archive_with_retry()` verschiebt Video und Marker.

---

## 6. Beschreibungs-Vorlagen (Eingabedaten für Job-Details)

Dateiname: `<beliebiger_name>-beschreibung.md` oder `<beliebiger_name>_beschreibung.md` im Zentralordner (`BESCHREIBUNG_DIR`, rekursive Suche möglich).

Aufbau (Markdown-Überschriften, Groß-/Kleinschreibung egal):

```markdown
# Titel
Sonnenuntergang über dem Alexanderplatz

# Beschreibung
Zeitraffer vom Herbstabend am Alexanderplatz.

# Tags
Berlin, Alexanderplatz, Sonnenuntergang, Herbst

# Aufnahmedatum
2026-09-20

# Sichtbarkeit
unlisted
```

`# Aufnahmedatum` und `# Sichtbarkeit` sind optional und überschreiben das automatisch ermittelte Datum bzw. `YOUTUBE_PRIVACY_STATUS` nur für dieses eine Video. Mehrzeilige Tags-Abschnitte werden vollständig zu einer kommagetrennten Liste zusammengeführt.

### Unterstützte Videoformate
- `*.MP4`: Pflichtformat für Finalrender und Aufnahmeerkennung.
- `*.LRV`: Optionales GoPro-Low-Resolution-Proxy für den Testrender.

### Anforderungen an die Videodaten
- Jeder zu verarbeitende Unterordner enthält mindestens eine lesbare MP4-Datei.
- Die zeitliche Reihenfolge basiert auf Dateisystem-Zeitstempeln, nicht auf Dateinamen.
- Das Aufnahmedatum wird bevorzugt aus dem `creation_time`-Metadatenfeld der ältesten MP4-Datei gelesen (bleibt beim Kopieren erhalten); nur falls dieses Feld fehlt, greift der Dateisystem-Zeitstempel als Fallback.

---

## 7. Ausgabedaten

| Ausgabe | Speicherort | Inhalt |
|---|---|---|
| Finalvideo | `OUTPUT_DIR` zunächst, danach `ARCHIVE_DIR` | `<Aufnahmeordner>_final.mp4` |
| Uploadmarker | Neben dem Video, nach Archivierung im Archiv | `<Aufnahmeordner>_final.mp4.uploaded.json` |
| Logdatei | `LOG_DIR` | `<YYYYMMDD_HHMMSS>.log` |
| Testrender-Vorschau | `TEMP_DIR` | `preview_<N>s.mp4`, wird nach Wiedergabe gelöscht |
| Kombiniertes Finalvideo (Zwischenschritt) | `TEMP_DIR` | `combined.mp4` |
| Concat-Liste | `TEMP_DIR` | `filelist.txt` |

Beispiel eines Uploadmarkers:
```json
{
  "youtube_video_id": "abc123",
  "source": "youtube_upload",
  "video_filename": "2026-09-20_11-58_final.mp4",
  "title": "2026-09-20 - Sonnenuntergang am Strand",
  "playlist_id": "PLEA5CC7D953EA20CF",
  "uploaded_at_utc": "2026-09-24T05:56:00Z"
}
```

---

## 8. Fehlerbehebung

| Fehlermeldung / Symptom | Ursache | Lösung |
|---|---|---|
| `gopro_config.py wurde nicht gefunden!` | Config liegt nicht neben dem Hauptskript | Beide Dateien in denselben Ordner legen |
| `Fehlender Konfigurationswert in gopro_config.py` | Pflichtparameter fehlt | Config mit erwarteten Parametern ergänzen |
| `VLC nicht gefunden` | VLC fehlt oder ist nicht im erwarteten Pfad | VLC installieren, `PATH` setzen oder `VLC_PATHS` anpassen |
| `Dauer von ... konnte nicht ermittelt werden` | ffprobe-Fehler oder beschädigte größte Testdatei | Datei prüfen; `ffprobe -version` kontrollieren |
| `FFmpeg Concat fehlgeschlagen` | FFmpeg fehlt, Quelldatei defekt oder Clips inkompatibel | `ffmpeg -version` prüfen, Material vereinheitlichen |
| `YouTube Client-Datei fehlt` | `YOUTUBE_CLIENT_SECRETS_FILE`-Pfad ist falsch | Pfad in `gopro_config.py` korrigieren |
| Encoder-Warnung `'...' funktioniert NICHT auf diesem System` | Konfigurierter Hardware-Encoder nicht verfügbar (Treiber/Hardware fehlt) | `FFMPEG_ENCODER = "auto"` setzen oder Treiber installieren |
| `Archivierung gesperrt` | Video/Marker wird von VLC/Explorer verwendet | Anwendungen schließen; Skript wiederholt automatisch bis zu sechsmal |

### Logs verstehen
Logs liegen in `logs/`, Format `<YYYYMMDD_HHMMSS>.log`. Jede Zeile enthält Zeit, Level und Nachricht. Zuerst nach `ERROR`, dann nach `WARNING` suchen.

---

## 9. FAQ

**Warum wird meine Aufnahme nicht angezeigt?**
Das Programm zeigt nur direkte Unterordner von `./aufnahmen/` an, die mindestens eine `.MP4`-Datei enthalten.

**Warum sieht der Testrender manchmal anders aus als erwartet?**
Der Testrender nutzt immer die **größte** LRV- (oder MP4-)Datei im Ordner, nicht mehrere zusammengefügte Clips – das vermeidet unvollständige Fehlstart-Clips als Quelle, kann aber bedeuten, dass ein anderer Abschnitt der Aufnahme gezeigt wird als beim Finalrender.

**Kann ich für jedes Video eine andere Playlist wählen?**
Nein. `YOUTUBE_PLAYLIST_ID` ist global in `gopro_config.py` definiert und gilt für alle Uploads eines Laufs.

**Werden Tags aus meiner Beschreibungs-Vorlage wirklich übernommen?**
Ja. Vor jedem Upload zeigt die Konsole die finale, tatsächlich gesendete Tag-Liste an (`🏷️ Finale Tags für diesen Upload: ...`), zusammengeführt aus `YOUTUBE_TAGS` und den Vorlagen-/manuellen Tags.

**Woher stammt das Datum im Titel?**
Aus dem `creation_time`-Metadatenfeld der ältesten MP4-Datei im Aufnahmeordner – nicht aus dem Datei-Kopierdatum. Nur wenn dieses Metadatenfeld fehlt, wird ersatzweise der Dateisystem-Zeitstempel verwendet (mit Warnung im Log).

**Was passiert, wenn der YouTube-Upload fehlschlägt?**
Das Finalvideo bleibt in `OUTPUT_DIR`. Beim nächsten Programmstart wird es automatisch als offener Upload erkannt und kann direkt nachgeholt werden – ohne erneutes Rendern.

---

## 10. Technische Referenz

### Klassen und Funktionen

| Element | Kurzbeschreibung |
|---|---|
| `Logger` | Duales Logging (Konsole + Datei), `error_and_exit()` für kritische Abbrüche. |
| `FFmpegHandler` | Encoder-Erkennung, Concatenieren, Rendern mit Fortschrittsanzeige, `get_creation_time()` für Metadaten. |
| `VLCPlayer` | Findet und startet VLC über `play()`. |
| `BeschreibungTemplateManager` | Findet und parsed Beschreibungs-Vorlagen. |
| `UploadMarker` | `marker_path()`, `write_marker()`, `read_marker()`. |
| `ArchiveManager` | `archive_with_retry()` mit bis zu sechs Wiederholungen. |
| `YouTubeUploader` | OAuth (`_get_credentials()`), `upload_video()`, `add_to_playlist()`. |
| `MenuDialog` | Alle interaktiven Menü- und Eingabeabfragen. |
| `GoProTimeLapseProcessor` | Koordiniert den gesamten Ablauf. |
| `main()` | Startpunkt des interaktiven Gesamtprozesses. |

### Wichtige Datenstrukturen
- `recordings`: `List[Tuple[str, str, str]]` – Ordnername, Startzeit, geschätzte Dauer.
- `_preview_source_cache`: `Dict[Tuple[str, str], Dict[str, Any]]` – Cache der größten Testrender-Quelldatei je (Ordner, Muster).
- Uploadmarker: UTF-8-JSON mit `youtube_video_id`, Titel, Playlist, UTC-Zeit.

### Erweiterungsmöglichkeiten
Automatisierte Tests (`pytest`) mit gemockten FFmpeg-/VLC-/YouTube-Aufrufen sind noch nicht vorhanden. Bei Erweiterungen sollten duales Logging, die Trennung von `gopro_config.py` und Hauptskript sowie die globale Playlist-Logik unverändert erhalten bleiben.
