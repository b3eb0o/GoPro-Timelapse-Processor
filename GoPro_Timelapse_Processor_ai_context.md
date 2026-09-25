```xml
<project_context>
  <meta>
    <project_name>GoPro Time-Lapse Vibe-Coding Processor</project_name>
    <version>2.0.23</version>
    <last_updated>2026-09-24</last_updated>
    <status>Beta</status>
    <complexity>Medium</complexity>
    <python_version>3.8+</python_version>
  </meta>

  <identity>
    <purpose>Verarbeitet GoPro Hero 5 Black 4K-Zeitrafferaufnahmen interaktiv zu beschleunigten MP4-Videos und veroeffentlicht diese automatisiert auf YouTube. Richtet sich an GoPro-Nutzer/Content-Creator, die einen lokalen, menuegesteuerten Windows-Workflow ohne manuelles Videoschnittprogramm bevorzugen.</purpose>
    <domain>Automatisierung / Videoverarbeitung</domain>
    <input_format>Unterordner unter ./aufnahmen/ mit GoPro-*.MP4-Dateien und optionalen *.LRV-Proxy-Dateien; externe gopro_config.py im selben Verzeichnis wie das Hauptskript; optionale *-beschreibung.md/*_beschreibung.md Vorlagen in einem Zentralordner.</input_format>
    <output_format>Finalvideo als MP4 in OUTPUT_DIR, anschliessend YouTube-Upload mit Playlist-Zuordnung, JSON-Uploadmarker (<video>.uploaded.json), Archivkopie in ARCHIVE_DIR, zeitgestempelte Logdatei in LOG_DIR pro Programmstart.</output_format>
  </identity>

  <architecture>
    <overview>Objektorientiert aufgebaut, orchestriert durch main() ueber die Fassade GoProTimeLapseProcessor. Beim Modulimport wird gopro_config.py geladen; fehlende Pflichtwerte beenden das Programm sofort. Die neun Klassen haben klar getrennte Verantwortlichkeiten: Logger (duales Logging), FFmpegHandler (Rendern, Encoder-Erkennung, Metadaten), VLCPlayer (Vorschau), BeschreibungTemplateManager (Markdown-Vorlagen), YouTubeUploader (OAuth + Upload), UploadMarker (Wiederanlauf-Marker), ArchiveManager (Archivierung mit Retry), MenuDialog (alle interaktiven Prompts), GoProTimeLapseProcessor (Koordination).</overview>
    <dataflow>aufnahmen/&lt;Ordner&gt;/*.MP4+*.LRV -> FFmpegHandler waehlt groesste Datei fuer Testrender -> adjust_speed_with_progress() -> temp/preview_Ns.mp4 -> VLCPlayer.play() zur Kontrolle -> nach Bestaetigung concat_files() ALLER MP4-Dateien -> temp/combined.mp4 -> Finalrender -> output/&lt;Ordner&gt;_final.mp4 -> YouTubeUploader.upload_video() (resumable) -> add_to_playlist() -> UploadMarker.write_marker() -> ArchiveManager.archive_with_retry() -> archiv/&lt;Ordner&gt;_final.mp4 + JSON-Marker.</dataflow>
    <key_components>
      <component name="GoProTimeLapseProcessor" type="class" purpose="Hauptkoordinator; haelt _preview_source_cache und delegiert an alle anderen Klassen" />
      <component name="FFmpegHandler" type="class" purpose="Encoder-Erkennung (_auto_detect_encoder, _probe_encoder_works), Concatenieren, Rendern mit Fortschrittsanzeige, Metadaten-Auslese (get_creation_time)" />
      <component name="YouTubeUploader" type="class" purpose="OAuth-Flow (_get_credentials, Token-Refresh-Persistenz), Video-Upload, Playlist-Zuordnung" />
      <component name="BeschreibungTemplateManager" type="class" purpose="Findet und parsed *-beschreibung.md/*_beschreibung.md Vorlagen nach '# Ueberschrift'-Abschnitten (Titel, Beschreibung, Tags, Aufnahmedatum, Sichtbarkeit)" />
      <component name="UploadMarker" type="class" purpose="Schreibt/liest atomare JSON-Marker (.uploaded.json) fuer den Resume-Upload-Mechanismus" />
      <component name="MenuDialog" type="class" purpose="Buendelt SAEMTLICHE interaktiven input()-Abfragen (FPS, Faktor, Testdauer, Job-Details, Bestaetigungen)" />
      <component name="render_preview" type="function" purpose="Waehlt IMMER die groesste LRV- (Fallback MP4-) Datei per max(files, key=size) als alleinige Testrender-Quelle" />
      <component name="derive_recording_date_from_folder" type="function" purpose="Ermittelt Aufnahmedatum: 1) YYYY-MM-DD-Praefix im Ordnernamen, 2) creation_time-Metadatentag der aeltesten MP4-Datei, 3) Fallback Dateisystem-mtime (mit Warnung)" />
    </key_components>
    <data_structures>
      <structure name="recordings" type="List[Tuple[str,str,str]]" description="Ordnername, Startzeit-String, geschaetzte Dauer-String fuer die Aufnahmeliste" />
      <structure name="uploadmarker_payload" type="dict (JSON)" description="youtube_video_id, source, video_filename, title, playlist_id, uploaded_at_utc" />
      <structure name="prefill" type="Dict[str,str]" description="Aus Beschreibungs-Vorlage geparste Felder: title, description, tags, recording_date, privacy_status" />
      <structure name="_preview_source_cache" type="Dict[Tuple[str,str], Dict[str,Any]]" description="Cache: (Ordnerpfad, Dateimuster) -> {path, duration, size_mb} der groessten Testrender-Quelldatei" />
    </data_structures>
  </architecture>

  <dependencies>
    <package name="google-api-python-client" version="nicht gepinnt" purpose="YouTube Data API v3 (videos().insert(), playlistItems().insert())" />
    <package name="google-auth-oauthlib" version="nicht gepinnt" purpose="OAuth-2.0-Flow fuer Desktop-Anwendungen (InstalledAppFlow)" />
    <package name="google-auth-httplib2" version="nicht gepinnt" purpose="Google-Auth-HTTP-Integration" />
    <package name="FFmpeg/ffprobe" version="extern, kein pip-Paket" purpose="Concatenieren, Zeitraffer-Rendering, Dauer- und Metadaten-Auslese via subprocess" />
    <package name="VLC" version="extern, kein pip-Paket" purpose="Vorschau-Wiedergabe via subprocess" />
  </dependencies>

  <configuration>
    <param name="YOUTUBE_CLIENT_SECRETS_FILE" type="str" default="Pflicht, kein Default" description="Pfad zur OAuth-Client-Datei" />
    <param name="YOUTUBE_TOKEN_FILE" type="str" default="Pflicht, kein Default" description="Pfad zur automatisch erzeugten Token-Datei" />
    <param name="YOUTUBE_PLAYLIST_ID" type="str" default="Pflicht, kein Default" description="Globale Ziel-Playlist fuer alle Uploads" />
    <param name="YOUTUBE_PRIVACY_STATUS" type="str" default="Pflicht" description="public / private / unlisted" />
    <param name="YOUTUBE_TAGS" type="list[str]" default="Pflicht" description="Standard-Tags, werden mit Vorlagen-/manuellen Tags gemerged" />
    <param name="BASE_DIR/OUTPUT_DIR/ARCHIVE_DIR/LOG_DIR/TEMP_DIR" type="str" default="leer = relativ zu BASE_DIR" description="Verzeichnisstruktur" />
    <param name="BESCHREIBUNG_DIR" type="str" default="leer = BASE_DIR/beschreibungen (getattr, optional)" description="Zentralordner fuer Beschreibungs-Vorlagen" />
    <param name="FFMPEG_ENCODER" type="str" default="'auto' (getattr, optional)" description="'auto', 'libx264' oder expliziter Hardware-Encoder-Name" />
    <param name="FFMPEG_PRESET" type="str" default="'' (getattr, optional)" description="Encoder-Preset, Gueltigkeit encoderabhaengig" />
    <param name="DEFAULT_TEST_PREVIEW_DURATION" type="int" default="20" description="Modul-Konstante (nicht in gopro_config.py), Standard-Testrender-Laenge in Sekunden" />
  </configuration>

  <conventions>
    <naming>Klassen PascalCase, Funktionen/Variablen snake_case, Modul-Konstanten UPPERCASE (z.B. HARDWARE_ENCODER_CANDIDATES)</naming>
    <error_handling>Kritische, nicht behebbare Fehler ueber Logger.error_and_exit() (Log + sys.exit(1)). Gezielt abgefangen: subprocess.CalledProcessError, FileNotFoundError, OSError, ValueError. YouTube-Upload-Fehler werden als generische Exception in main() gefangen OHNE Programmabbruch (Video bleibt in OUTPUT_DIR fuer Resume-Upload erhalten).</error_handling>
    <logging>Logger.log(message, level="INFO") schreibt IMMER gleichzeitig auf Konsole und in logs/&lt;YYYYMMDD_HHMMSS&gt;.log (eine Datei pro Programmstart), UTF-8.</logging>
    <file_io>Pathlib (Path) durchgaengig statt os.path. JSON-Dateien UTF-8 mit ensure_ascii=False. Uploadmarker werden atomar geschrieben (.part-Datei + os.replace()).</file_io>
    <code_style>Durchgehend deutsche Docstrings ("""..."""). Type Hints konsequent genutzt (List, Tuple, Optional, Dict, Any aus typing). Bestehende Klassen und oeffentliche Methodensignaturen sollen bei Aenderungen stabil bleiben.</code_style>
  </conventions>

  <known_issues>
    <issue severity="critical">Kein Retry/Backoff fuer YouTube-API-Fehler (Netzwerk/Quota) - Upload muss manuell ueber den Resume-Mechanismus neu angestossen werden.</issue>
    <issue severity="medium">VLCPlayer.VLC_PATHS enthaelt ausschliesslich Windows-Pfade; andere Betriebssysteme benoetigen VLC im PATH.</issue>
    <issue severity="medium">Keine automatisierten Tests (kein pytest/unittest-Paket im Projekt vorhanden).</issue>
    <issue severity="low">Fehlt das creation_time-Metadatenfeld in einer Videodatei, greift der Fallback auf den Dateisystem-Zeitstempel (mit Warnung geloggt, aber potenziell ungenau).</issue>
  </known_issues>

  <open_todos>
    <todo priority="high">YouTube-Retry mit Exponential Backoff fuer temporaere Netzwerk-/Quota-Fehler ergaenzen.</todo>
    <todo priority="medium">pytest-Suite mit Mocks fuer FFmpeg/VLC/YouTube aufsetzen (tests/test_upload_marker.py, tests/test_ffmpeg_handler.py, tests/test_archive_manager.py).</todo>
    <todo priority="low">Batch-Modus fuer mehrere Aufnahmeordner in einem Programmlauf.</todo>
  </open_todos>

  <changelog>
    <entry date="2026-09-23">v2.0.23: Aufnahmedatum wird aus Video-Metadaten (creation_time) statt Dateisystem-Zeitstempel gelesen; Tags aus Beschreibungs-Vorlage werden vollstaendig (auch mehrzeilig) uebernommen und vor dem Upload sichtbar bestaetigt.</entry>
    <entry date="2026-09-22">v2.0.20-2.0.22: Fix fuer eingefrorenes Bild bei Concat-Nahtstellen (-fflags +genpts); Testrender verwendet ausschliesslich die groesste LRV-/MP4-Datei statt mehrerer concatenierter Dateien.</entry>
    <entry date="2026-09-19">v2.0.16-2.0.19: Beschreibungs-Vorlagen aus Zentralordner eingefuehrt; automatische Hardware-Encoder-Erkennung (NVENC/QSV/AMF) per echtem Testencode ergaenzt.</entry>
  </changelog>

  <ai_instructions>
    <instruction>Beim Modifizieren: Bestehende Code-Konventionen (deutsche Docstrings, snake_case, Path statt os.path) exakt beibehalten</instruction>
    <instruction>Vor jeder Aenderung: Betroffene Funktionen/Klassen und potenzielle Seiteneffekte explizit benennen</instruction>
    <instruction>Immer vollstaendige Funktionen/Klassen ausgeben, keine Fragmente oder Platzhalter</instruction>
    <instruction>Bei fachlichen Unklarheiten: Nachfragen statt Annahmen treffen</instruction>
    <instruction>Dual Logging erhalten: relevante Ereignisse gehoeren IMMER gleichzeitig in Konsole und Logdatei (Logger.log())</instruction>
    <instruction>Bei FFmpeg-Aenderungen: -fflags +genpts, Fortschrittsanzeige und Encoder/Preset-Logik (self.encoder, self.preset) nicht ohne Ruecksprache entfernen</instruction>
    <instruction>Neue Python-Abhaengigkeiten nur nach expliziter Zustimmung einfuehren; bevorzugt Standardbibliothek und bereits genutzte Google-Pakete verwenden</instruction>
    <instruction>Fuer neue/geaenderte Logik passende Testfaelle vorschlagen; externe Prozesse (FFmpeg, VLC, YouTube-API) in Tests mocken</instruction>
    <instruction>Nach Codeaenderungen: Benutzeranleitung und Projektbeschreibung auf Aktualisierungsbedarf pruefen und bei Bedarf konsistent nachfuehren</instruction>
    <instruction>Alle Ausgaben, Kommentare und Docstrings im Code auf Deutsch verfassen (bestehende Sprachkonvention)</instruction>
  </ai_instructions>
</project_context>
```
