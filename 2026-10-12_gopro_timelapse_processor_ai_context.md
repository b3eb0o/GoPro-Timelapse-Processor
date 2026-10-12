```xml
<project_context>
  <meta>
    <project_name>GoPro Time-Lapse Vibe-Coding Processor</project_name>
    <version>2.4.1</version>
    <last_updated>2026-10-12</last_updated>
    <status>Beta</status>
    <complexity>Large</complexity>
    <python_version>&gt;=3.8 (Path.unlink(missing_ok=True))</python_version>
  </meta>

  <identity>
    <purpose>Interaktives Konsolenskript: fügt GoPro-Hero-5-Black-Zeitraffer (mehrere Chapter je Aufnahmeordner) per FFmpeg in einem Durchgang zusammen, rafft und encodiert sie, lädt sie auf YouTube hoch, schreibt einen Uploadmarker und archiviert. Einzelnutzer-Werkzeug auf Windows; Ziel: vollständiges Video ohne manuelle Zwischenschritte. Modus -u lädt fertige Videos im Stapel hoch.</purpose>
    <domain>Automatisierung</domain>
    <input_format>Aufnahmeordner mit GOPRnnnn.MP4 / GPccnnnn.MP4 (+ optional *.LRV); gopro_config.ini; Vorlagen *-beschreibung.md / *_beschreibung.md; Konsoleneingaben; CLI -u, --dry-run, -h, --version</input_format>
    <output_format>output/&lt;Ordner&gt;_final.mp4 (H.264, yuv420p, ohne Ton); YouTube-Video; &lt;video&gt;.mp4.uploaded.json; .gopro-media-index.json je Aufnahmeordner; logs/YYYYMMDD_HHMMSS.log; gopro_config.ini(.bak) bei geänderter Ziel-FPS</output_format>
  </identity>

  <architecture>
    <overview>Ein Modul. main(): parse_arguments → load_configuration (ggf. migrate_legacy_config) → ensure_external_tools → run_full_mode oder run_upload_mode. GoProTimeLapseProcessor orchestriert Logger, FFmpegHandler, VLCPlayer, BeschreibungTemplateManager, MenuDialog, YouTubeUploader, UploadMarker, ArchiveManager. Konsolenausgabe nur über das globale UI-Singleton ui. Seit v2.4.0 keine Zwischendatei combined.mp4 (concat-Filter statt Stream-Copy-Concat).</overview>
    <dataflow>list_recordings/_get_media_data → estimate_span → VLC-Vorschau → render_preview (Faktor-Schleife) → get_job_details + validate_youtube_metadata → confirm_job → render_final/render_from_files → Vollständigkeitsprüfung → upload_video → finalize_after_upload (Marker, Archiv) → save_ziel_fps</dataflow>
    <key_components>
      <component name="Config" type="class" purpose="INI typisiert laden, validate, save_ziel_fps zeilengenau mit .bak" />
      <component name="ENCODER_PROFILES" type="config" purpose="Übersetzung qualitaet/tempo in encoderspezifische FFmpeg-Parameter" />
      <component name="FFmpegHandler" type="class" purpose="Encoder-Erkennung, Test-/Finalrender, ffprobe, _run_with_progress mit stderr-Thread" />
      <component name="GoProTimeLapseProcessor" type="class" purpose="Orchestrierung, Medienindex, Wanduhrzeit, Stapelupload" />
      <component name="MenuDialog" type="class" purpose="Alle interaktiven Abfragen und Bestätigungen" />
      <component name="YouTubeUploader" type="class" purpose="OAuth, resumable Upload (8 MiB, 5 Retries), Playlist" />
      <component name="UploadMarker" type="class" purpose="*.uploaded.json mit Upload-Historie" />
      <component name="ArchiveManager" type="class" purpose="Verschieben ins Archiv mit Retry und Konfliktnamen" />
      <component name="BeschreibungTemplateManager" type="class" purpose="Vorlagen: # Titel, # Beschreibung, # Tags, # Aufnahmedatum, # Sichtbarkeit" />
    </key_components>
    <data_structures>
      <structure name="recordings" type="list[dict]" description="name, start, span_seconds, span_ratio, material_seconds, file_count (+ *_str)" />
      <structure name=".gopro-media-index.json" type="JSON" description="schema_version=1, files{Name:{size, mtime_ns, duration_seconds}}, summary; keine Nullwerte" />
      <structure name="*.uploaded.json" type="JSON" description="youtube_video_id (jüngster), upload_count, uploads[] (Historie)" />
      <structure name="upload candidate / batch entry" type="dict" description="path, origin_short A/O, in_archive, size_mb, marker (+ recording_date, period_str, title, description, tags, privacy)" />
    </data_structures>
  </architecture>

  <dependencies>
    <package name="google-api-python-client" version="ungepinnt" purpose="YouTube Data API v3, MediaFileUpload" />
    <package name="google-auth" version="ungepinnt" purpose="Credentials, Request (Token-Refresh)" />
    <package name="google-auth-oauthlib" version="ungepinnt" purpose="InstalledAppFlow (Browser-Login)" />
    <package name="ffmpeg / ffprobe" version="PATH" purpose="Pflicht; Render und Analyse" />
    <package name="VLC" version="optional" purpose="Vorschau; fehlt VLC, wird übersprungen" />
  </dependencies>

  <configuration>
    <param name="[YouTube] client_secrets_file / token_file" type="Pfad" default="Pflicht" description="OAuth-Dateien" />
    <param name="[YouTube] privacy_status / tags" type="str / Liste" default="private / Zeitraffer, GoPro" description="public|private|unlisted, sonst harter Fehler" />
    <param name="[YouTube] category_id / license / playlist_id" type="str" default="19 / youtube / leer" description="license: youtube|creativeCommon" />
    <param name="[YouTube] public_stats_viewable / embeddable / made_for_kids / contains_synthetic_media" type="bool" default="true/true/false/false" description="Upload-Status" />
    <param name="[Verzeichnisse] basis_dir" type="Pfad" default="Skriptordner" description="leere *_dir = basis/aufnahmen|output|archiv|logs|temp|beschreibungen" />
    <param name="[Render] encoder" type="str" default="auto" description="auto|libx264|h264_nvenc|h264_qsv|h264_amf|h264_videotoolbox" />
    <param name="[Render] qualitaet / tempo" type="str" default="hoch / schnell" description="niedrig..maximal / sehr schnell..langsam" />
    <param name="[Render] ziel_fps / ziel_fps_merken" type="int / bool" default="0 / true" description="0-240; wird nach erfolgreichem Lauf zurückgeschrieben" />
    <param name="[Ablauf] testrender_dauer / erste_vorschau_dauer" type="int" default="20 / 20" description="1-300 / 1-600 Sekunden" />
    <param name="[Ablauf] archiv_versuche / archiv_wartezeit" type="int" default="6 / 10" description="1-100 / 0-600 s" />
    <param name="[Ablauf] temp_auto_cleanup / materiallaenge_in_liste" type="bool" default="true / true" description="temp_auto_cleanup ungenutzt" />
    <param name="[Anzeige] farben / symbole / ausfuehrlich / breite" type="bool/int" default="true / true / false / 78" description="breite 40-200" />
  </configuration>

  <conventions>
    <naming>snake_case, PascalCase (Klassen), UPPER_CASE (Konstanten); Bezeichner gemischt deutsch/englisch</naming>
    <error_handling>ConfigError + sys.exit(1); Logger.error_and_exit für fatale Fehler; ffprobe-Fehler → 0.0/None + WARNING; Upload-Exceptions im Aufrufer gefangen; Marker-/Archivfehler nie als Uploadfehler melden; Strg+C → Code 0</error_handling>
    <logging>Klasse Logger, Datei je Lauf, "YYYY-MM-DD HH:MM:SS - LEVEL - Meldung", INFO/WARNING/ERROR; Konsole nur bei console=True oder ausfuehrlich=true</logging>
    <file_io>pathlib; UTF-8; JSON ensure_ascii=False, indent=2; Schreiben über .part/.tmp + os.replace; INI nie per configparser.write()</file_io>
    <code_style>Docstrings mit Begründung und Versionsbezug ("NEU in v2.4.0"); Typehints fast durchgängig; Banner "# ====="; Konsolentexte/Kommentare deutsch mit ae/oe/ue/ss statt Umlauten; YouTube-Beschreibungskopf englisch (build_description)</code_style>
  </conventions>

  <known_issues>
    <issue severity="critical">Render direkt auf &lt;Ordner&gt;_final.mp4; Abbruch hinterlässt Teildatei, die als offener Upload erscheint</issue>
    <issue severity="critical">Als unvollständig erkannte Ausgabe wird ohne Rückfrage hochgeladen</issue>
    <issue severity="medium">--dry-run schreibt Log, Verzeichnisse und ggf. .gopro-media-index.json</issue>
    <issue severity="medium">Archiv-Duplikat: Quelle gelöscht, Marker mit neuer ID verwaist</issue>
    <issue severity="medium">RefreshError beim Token-Refresh nicht abgefangen</issue>
    <issue severity="medium">render_final globbt nur *.MP4 (Problem auf Linux/macOS)</issue>
    <issue severity="low">Ungenutzt: temp_auto_cleanup, limit_files, _material_cache, get_total_source_duration_for_video; Docstring-Datum 2026-09-26 vs. __DATUM__ 2026-10-12</issue>
  </known_issues>

  <open_todos>
    <todo priority="high">Render in .part-Datei, Umbenennen erst nach bestandener Vollständigkeitsprüfung</todo>
    <todo priority="medium">--dry-run nebenwirkungsfrei; RefreshError → Browser-Login</todo>
    <todo priority="medium">Faktor/FPS persistieren (Wanduhrzeit beim Archiv-Upload)</todo>
    <todo priority="low">Toten Code bereinigen; pytest; Modularisierung</todo>
  </open_todos>

  <changelog>
    <entry date="2026-10-12">v2.4.1: Persistenter Medienindex .gopro-media-index.json (Validierung Name/size/mtime_ns)</entry>
    <entry date="unbekannt">v2.4.0: Ein-Pass-Render per concat-Filter, combined.mp4 entfällt, Prüfung der Ausgabe gegen Summe/Faktor</entry>
    <entry date="unbekannt">v2.1.x–v2.3.1: GOPR als Chapter 0, Encoder-Profile, INI mit Migration, Ziel-FPS, Stapel-Upload -u, --dry-run, Marker-Historie, Wanduhrzeit inkl. erstem Chapter</entry>
  </changelog>

  <ai_instructions>
    <instruction>Beim Modifizieren: Bestehende Code-Konventionen exakt beibehalten</instruction>
    <instruction>Vor jeder Änderung: Betroffene Funktionen und potenzielle Seiteneffekte benennen</instruction>
    <instruction>Immer vollständige Funktionen/Klassen ausgeben, keine Fragmente oder Platzhalter</instruction>
    <instruction>Bei Unklarheiten: Nachfragen statt Annahmen treffen</instruction>
    <instruction>CSV-Verarbeitung: entfällt (keine CSV); für INI/JSON/Markdown analog: UTF-8, atomares Schreiben, Fehlerbehandlung wie im Bestand</instruction>
    <instruction>Visualisierungen: entfällt (keine Plots); Konsolenstil der Klasse UI (Symbole, Farben, kv/step/section) beibehalten</instruction>
    <instruction>Neue Abhängigkeiten nur nach expliziter Rückfrage einführen</instruction>
    <instruction>Bei Änderungen am Code: Benutzeranleitung auf Aktualisierungsbedarf prüfen und ggf. aktualisierte Version der Benutzeranleitung ausgeben</instruction>
    <instruction>Alle Ausgaben und Kommentare im Code in der Sprache des bestehenden Codes verfassen</instruction>
    <instruction>__VERSION__, __DATUM__, __BESCHREIBUNG__ pflegen; Bereinigungen = +0.0.1; INI-Kopf "Passend zu Skript-Version" angleichen</instruction>
    <instruction>Nicht-triviale Änderungen: erst Konzeptmodus (Fragen, Vorschläge), Umsetzung nach Freigabe</instruction>
    <instruction>Fail-closed: kein Upload, Überschreiben oder Löschen ohne Prüfung/Bestätigung</instruction>
    <instruction>Erzeugte Dateien mit Präfix YYYY-TT-MM__HHMM_ (Berlin); das Skript erwartet gopro_config.ini ohne Präfix</instruction>
  </ai_instructions>
</project_context>
```
