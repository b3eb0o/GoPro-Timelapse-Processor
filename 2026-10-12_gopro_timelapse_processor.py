#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GoPro Time-Lapse Vibe-Coding Processor
Verarbeitet GoPro Hero 5 Black Zeitrafferaufnahmen mit interaktiver
Menue-Fuehrung, YouTube-Upload, Archivierung und Uploadmarker.

Version: 2.4.1
Datum: 2026-09-26
"""

__VERSION__ = "2.4.1"
__DATUM__ = "2026-10-12"
__BESCHREIBUNG__ = (
    "v2.4.1 - PERSISTENTER MEDIENINDEX: Materiallaengen werden je Aufnahmeordner "
    "in .gopro-media-index.json gespeichert. Nur neue oder geaenderte MP4-Dateien "
    "werden erneut mit ffprobe geprueft; Validierung ueber Dateiname, Groesse und "
    "mtime_ns. Fehlerhafte Nullwerte werden nicht dauerhaft gespeichert. "
    "Aus v2.4.0: EIN-PASS-RENDER statt Zwischendatei: "
    "Der Finalrender lief bisher in zwei Schritten - erst ein verlustfreier "
    "Concat aller Chapter nach combined.mp4, danach der eigentliche Render "
    "mit setpts. Dieser Zwischenschritt war die einzige Stelle im gesamten "
    "Ablauf, an der stillschweigend Material verschwinden konnte: FFmpegs "
    "Stream-Copy-Concat bricht bei GoPro-Containern unter bestimmten "
    "Bedingungen vorzeitig ab, meldet aber trotzdem Exit-Code 0. Im Ordner "
    "2026-09-25 gingen so 550 von 744 Sekunden verloren (74 Prozent) - der "
    "Concat endete unmittelbar nach dem ersten 0,16s-Chapter. "
    "Die Zwischendatei war ausserdem UEBERFLUESSIG, da danach ohnehin neu "
    "encodiert wurde (setpts, neue FPS, neuer Encoder), und kostete "
    "Schreiblast in Groesse des gesamten Quellmaterials (6-9 GB je Lauf). "
    "Ab v2.4.0 werden alle Chapter direkt als Eingaenge geoeffnet, per "
    "concat-FILTER zusammengefuegt und in EINEM Durchgang zeitgerafft und "
    "encodiert. Der Filter dekodiert jede Datei einzeln und normalisiert sie "
    "vor dem Aneinanderhaengen - er kann strukturell nichts verlieren. "
    "Verifiziert mit nachgebautem Material des betroffenen Ordners: "
    "743,85s Quelle -> 124,03s Ergebnis bei Faktor 6 (erwartet 123,97s). "
    "Weitere Anpassungen: Die Vollstaendigkeitspruefung prueft jetzt die "
    "AUSGABEDATEI gegen 'Summe Quelldauern / Faktor' (vorher die "
    "Zwischendatei gegen die Summe der Quelldauern). Die Zielaufloesung "
    "ergibt sich aus der ersten Datei; abweichende Chapter werden gemeldet "
    "und eingepasst. combined.mp4 entfaellt ersatzlos. "
    "Aus v2.3.1 unveraendert: Wanduhrzeit inkl. erstem Chapter, "
    "einheitliche Anzeige von Zeitraum und Materiallaenge. "
    "Aus v2.3.0: Stapel-Uploadmodus (-u), englische Beschreibungen, "
    "Uploadmarker mit Historie, Kommandozeile mit --dry-run. "
    "Aus v2.2.0: INI-Konfiguration mit Migration, Ziel-FPS als Vorbelegung, "
    "aufgeraeumte Konsole. "
    "Aus v2.1.x: GOPR-Namensschema als Chapter 0, abstraktes Encoder-Profil, "
    "Rendern ohne Tonspur, Upload mit Chunk-Fortschritt und Retry"
)

# Console-Encoding fixen (Windows UTF-8)
import sys
import io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace',
                                  line_buffering=True, write_through=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace',
                                  line_buffering=True, write_through=True)

import os
import re
import json
import time
import shutil
import threading
import subprocess
import configparser
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

# Windows-Konstanten fuer subprocess
SW_SHOWNORMAL = 1
STARTF_USESHOWWINDOW = 0x00000001

# YouTube-Limits (API-seitig hart; ohne Vorabpruefung faellt ein Verstoss
# erst beim Upload auf - also nach dem stundenlangen Render).
YT_MAX_TITLE_LEN = 100
YT_MAX_DESCRIPTION_LEN = 5000
YT_MAX_TAGS_TOTAL_LEN = 500

VALID_PRIVACY = ("public", "private", "unlisted")
VALID_LICENSE = ("youtube", "creativeCommon")

# ----------------------------------------------------------------------------
# Plausibilitaetsgrenzen fuer das aus den Zeitstempeln abgeleitete
# Zeitraffer-Verhaeltnis der Kamera (seit v2.3.1).
#
# Unterhalb von 1 waere die Wanduhrzeit kuerzer als das Videomaterial (bei
# einem Zeitraffer unmoeglich), oberhalb von 500 lagen die Chapter so weit
# auseinander, dass die Zeitstempel vermutlich verfaelscht sind (z.B. durch
# ein Kopierwerkzeug, das mtime nicht erhaelt). In beiden Faellen wird nicht
# hochgerechnet, sondern der ungekorrigierte Wert verwendet.
# ----------------------------------------------------------------------------
SPAN_RATIO_MIN = 1.0
SPAN_RATIO_MAX = 500.0

# ----------------------------------------------------------------------------
# GoPro-Dateinamensschema
#
# Die Hero 5 verwendet ZWEI Schemata innerhalb derselben Aufnahme:
#   GOPR1290.MP4  -> das ERSTE Chapter (implizit Chapter 0)
#   GP011290.MP4  -> Chapter 1,  GP021290.MP4 -> Chapter 2 ...
# Beide muessen erkannt werden, sonst faellt die Sortierung auf die
# unzuverlaessige Zeitstempel-Reihenfolge zurueck (Fix aus v2.1.1).
# ----------------------------------------------------------------------------
GOPRO_CHAPTER_RE = re.compile(r"^(G[PXHLO])(\d{2})(\d{4})$", re.IGNORECASE)
GOPRO_FIRST_RE = re.compile(r"^(GOPR)(\d{4})$", re.IGNORECASE)

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_INI = SCRIPT_DIR / "gopro_config.ini"
CONFIG_PY_LEGACY = SCRIPT_DIR / "gopro_config.py"
MEDIA_INDEX_FILENAME = ".gopro-media-index.json"
MEDIA_INDEX_SCHEMA_VERSION = 1


# ============================================================================
# Formatierung von Zeitangaben
# ============================================================================

def format_hms(seconds: float) -> str:
    """Formatiert Sekunden als 'Xh Ym Zs' / 'Ym Zs' / 'Zs' (kuerzeste Form)."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_h_min(seconds: float) -> str:
    """Formatiert Sekunden als 'Xh Ymin' - fuer Wanduhr-Zeitspannen."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    return f"{hours}h {rem // 60}min"


def format_span(seconds: float) -> str:
    """Formatiert eine Wanduhr-Zeitspanne, mit 'unbekannt' bei 0.

    Seit v2.3.1 die einzige Quelle fuer Aufnahmeliste UND Schritt 2/8 -
    vorher zeigte die Liste '0h 0min', wo Schritt 2/8 'unbekannt' meldete.

    'unbekannt' ist inhaltlich richtig: Bei einer einzelnen Datei gibt es
    keinen Zeitstempel-Abstand, aus dem sich die Wanduhrzeit ableiten liesse.
    '0h 0min' wuerde dagegen behaupten, die Aufnahme habe keine Zeit gedauert,
    obwohl Videomaterial vorhanden ist.
    """
    return format_h_min(seconds) if seconds > 0 else "unbekannt"


def format_material_len(seconds: float) -> str:
    """Formatiert Videomateriallaengen als 'Xmin Ys' bzw. 'Xh Ymin Zs'.

    Bewusst getrennt von format_h_min(): dort ergaebe typisches
    Zeitraffer-Material immer '0h 14min' - die fuehrende Null hat den
    Eindruck verstaerkt, es fehle Material.
    """
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes}min {secs}s"
    return f"{minutes}min {secs}s"


def normalize_key(value: str) -> str:
    """Normalisiert Schluesselwoerter: Kleinschreibung, Umlaute, Trennzeichen."""
    value = (value or "").strip().lower()
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        value = value.replace(src, dst)
    return re.sub(r"[\s\-]+", "_", value)


# ============================================================================
# YouTube-Beschreibung (englisch)
# ============================================================================

def build_description(recording_date: str, body: str, period_str: str = "") -> str:
    """Baut die YouTube-Beschreibung aus Kopfbereich und Textkoerper.

    Der Kopfbereich ist durchgaengig englisch. Die Zeitangabe ist die
    WANDUHRZEIT der Aufnahme ('Recording period'), also der reale Zeitraum,
    ueber den die Kamera aufgenommen hat - nicht die Laenge des
    Videomaterials. Bei einem Zeitraffer sind das voellig verschiedene Werte
    (im Produktivmaterial 12h 26min gegenueber 14min 56s).

    Laesst sich der Quellordner nicht mehr finden (typisch beim Upload aus
    dem Archiv), entfaellt die Zeile ersatzlos. Eine Rueckrechnung aus
    Videolaenge mal Faktor waere nicht moeglich, da der Faktor nirgends
    gespeichert wird.

    Diese Funktion ist bewusst die EINZIGE Stelle, an der der Kopfbereich
    entsteht - vorher gab es dafuer zwei getrennte Zweige (manuelle Eingabe
    und Vorlage), die auseinanderlaufen konnten.
    """
    header = [
        f"Recorded on {recording_date}",
        "GoPro Hero 5 Black, 4K time-lapse",
    ]
    if period_str:
        header.append(f"Recording period: {period_str}")

    body = (body or "").strip()
    return "\n".join(header) + ("\n\n" + body if body else "")


# ============================================================================
# Auswahl-Syntax (Bereiche)
# ============================================================================

def parse_selection(raw: str, count: int) -> Optional[List[int]]:
    """Wertet eine Auswahl wie '1,3', '2-5' oder '1,4-6' aus.

    Rueckgabe: Liste von 0-basierten Indizes (ohne Dubletten) oder None,
    wenn die Eingabe nicht verwertbar war.
    """
    if not raw:
        return None

    indices: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue

        range_match = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start > end:
                start, end = end, start
            for number in range(start, end + 1):
                if 1 <= number <= count:
                    indices.append(number - 1)
            continue

        if part.isdigit():
            number = int(part)
            if 1 <= number <= count:
                indices.append(number - 1)
            continue

        # Unverwertbarer Bestandteil - die gesamte Eingabe gilt als ungueltig,
        # damit nicht versehentlich eine Teilmenge hochgeladen wird.
        return None

    if not indices:
        return None

    seen = set()
    unique: List[int] = []
    for index in indices:
        if index not in seen:
            seen.add(index)
            unique.append(index)
    return unique


# ============================================================================
# Konsolenausgabe
# ============================================================================

class UI:
    """Zentrale Bildschirmausgabe.

    Buendelt Breite, Farben, Symbole und Ausfuehrlichkeit an einer Stelle.
    Wird beim Start aus dem Abschnitt [Anzeige] der INI konfiguriert.
    """

    _RESET = "\033[0m"
    _BOLD = "\033[1m"
    _DIM = "\033[2m"
    _RED = "\033[31m"
    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _BLUE = "\033[36m"

    SYMBOLS = {
        "ok": ("✅", "[OK]"),
        "warn": ("⚠️ ", "[!] "),
        "err": ("❌", "[X]"),
        "info": ("ℹ️ ", "[i] "),
        "film": ("🎬", "[>]"),
        "folder": ("📁", "[D]"),
        "up": ("📤", "[^]"),
        "box": ("📦", "[#]"),
        "clock": ("⏱️ ", "[T] "),
        "gear": ("⚙️ ", "[*] "),
        "note": ("📝", "[=]"),
        "chart": ("📊", "[%]"),
        "search": ("🔍", "[?]"),
        "play": ("▶️ ", "[>] "),
        "rocket": ("🚀", "[^]"),
        "wave": ("👋", "[.]"),
        "test": ("🧪", "[~]"),
    }

    def __init__(self):
        self.width = 78
        self.use_color = False
        self.use_symbols = True
        self.verbose = False

    def configure(self, width: int = 78, color: bool = True,
                  symbols: bool = True, verbose: bool = False) -> None:
        self.width = max(40, min(200, width))
        self.use_symbols = symbols
        self.verbose = verbose
        self.use_color = color and self._color_supported()

    @staticmethod
    def _color_supported() -> bool:
        """Prueft, ob ANSI-Farben sinnvoll nutzbar sind."""
        if not sys.stdout.isatty():
            return False
        if os.environ.get("NO_COLOR"):
            return False
        if sys.platform == "win32":
            # Windows 10 ab 1511 kann ANSI, muss aber freigeschaltet werden.
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                return True
            except Exception:
                return False
        return True

    # -- Bausteine ---------------------------------------------------------

    def sym(self, name: str) -> str:
        emoji, plain = self.SYMBOLS.get(name, ("", ""))
        return emoji if self.use_symbols else plain

    def _c(self, text: str, code: str) -> str:
        return f"{code}{text}{self._RESET}" if self.use_color else text

    def rule(self, char: str = "=") -> None:
        print(char * self.width)

    def header(self, text: str, symbol: str = "") -> None:
        prefix = f"{self.sym(symbol)} " if symbol else ""
        print()
        self.rule("=")
        print(self._c(f"{prefix}{text}", self._BOLD))
        self.rule("=")

    def section(self, text: str, symbol: str = "") -> None:
        prefix = f"{self.sym(symbol)} " if symbol else ""
        print()
        print(self._c(f"{prefix}{text}", self._BOLD))
        self.rule("-")

    # -- Meldungen ---------------------------------------------------------

    def ok(self, text: str) -> None:
        print(f"{self.sym('ok')} {self._c(text, self._GREEN)}")

    def warn(self, text: str) -> None:
        print(f"{self.sym('warn')} {self._c(text, self._YELLOW)}")

    def error(self, text: str) -> None:
        print(f"{self.sym('err')} {self._c(text, self._RED)}")

    def info(self, text: str) -> None:
        print(f"{self.sym('info')} {text}")

    def plain(self, text: str = "") -> None:
        print(text)

    def detail(self, text: str) -> None:
        print(f"   {self._c(text, self._DIM)}")

    def kv(self, key: str, value: Any, width: int = 32) -> None:
        print(f"  {key:<{width}}: {self._c(str(value), self._BOLD)}")

    def step(self, current: int, total: int, text: str) -> None:
        label = self._c(f"Schritt {current}/{total}", self._BLUE)
        print()
        self.rule("=")
        print(f"{label}  {self._c(text, self._BOLD)}")
        self.rule("=")

    def progress_bar(self, percent: int, length: int = 30) -> str:
        percent = max(0, min(100, percent))
        filled = int(length * percent / 100)
        if self.use_symbols:
            return "█" * filled + "░" * (length - filled)
        return "#" * filled + "-" * (length - filled)

    def clear_line(self) -> None:
        """Loescht die aktuelle Zeile - verhindert Balkenreste bei Warnungen."""
        print("\r" + " " * (self.width - 1), end="\r")


ui = UI()


# ============================================================================
# Kommandozeile
# ============================================================================

HELP_TEXT = """
GoPro Time-Lapse Vibe-Coding Processor v{version}

AUFRUF
  python gopro_timelapse_processor.py [OPTIONEN]

OPTIONEN
  (ohne)            Vollstaendiger Ablauf: Aufnahme waehlen, Faktor testen,
                    rendern, hochladen, archivieren.

  -u, --upload      Uploadmodus. Rendert NICHT, sondern laedt bereits
                    fertige Videos hoch. Scannt Archiv- und Ausgabeordner,
                    laesst eine Auswahl treffen, fragt Beschreibungs-Vorlage
                    und Sichtbarkeit EINMAL ab und arbeitet den Stapel dann
                    ohne weitere Eingabe ab.

      --dry-run     Nur anzeigen, was passieren wuerde. Es wird nichts
                    hochgeladen, verschoben oder geschrieben. Sinnvoll in
                    Kombination mit -u, bevor ein grosser Stapel laeuft.

  -h, --help        Diese Hilfe anzeigen.
      --version     Versionsnummer anzeigen.

BEISPIELE
  python gopro_timelapse_processor.py
      Normaler Ablauf mit Rendern.

  python gopro_timelapse_processor.py -u
      Fertige Videos aus Archiv und Ausgabeordner hochladen.

  python gopro_timelapse_processor.py -u --dry-run
      Vorschau des Stapel-Uploads, ohne etwas zu veraendern.

KONFIGURATION
  Alle Einstellungen stehen in gopro_config.ini neben diesem Skript.
"""


class Options:
    """Ausgewertete Kommandozeilenargumente."""

    def __init__(self):
        self.upload_mode = False
        self.dry_run = False


def parse_arguments(argv: List[str]) -> Options:
    """Wertet die Kommandozeile aus.

    Bewusst von Hand statt mit argparse: der Bedarf ist klein, und so bleibt
    die Hilfe im gleichen Stil wie die uebrige Konsolenausgabe (deutsch,
    mit Beispielen) statt im argparse-Standardformat.
    """
    options = Options()

    for argument in argv:
        lowered = argument.lower()

        if lowered in ("-h", "--help", "/?", "-?"):
            print(HELP_TEXT.format(version=__VERSION__))
            sys.exit(0)

        if lowered in ("--version", "-v"):
            print(f"GoPro Time-Lapse Processor {__VERSION__} ({__DATUM__})")
            sys.exit(0)

        if lowered in ("-u", "--upload"):
            options.upload_mode = True
            continue

        if lowered in ("--dry-run", "--dryrun", "-n"):
            options.dry_run = True
            continue

        ui.error(f"Unbekannte Option: {argument}")
        ui.plain("   Mit '-h' werden alle Optionen angezeigt.")
        sys.exit(1)

    return options


# ============================================================================
# Konfiguration (INI)
# ============================================================================

class ConfigError(Exception):
    """Fehler beim Laden oder Auswerten der Konfiguration."""


class Config:
    """Laedt gopro_config.ini und stellt die Werte typisiert bereit."""

    BOOL_TRUE = ("true", "yes", "ja", "an", "on", "1")
    BOOL_FALSE = ("false", "no", "nein", "aus", "off", "0")

    def __init__(self, path: Path):
        self.path = path
        self.parser = configparser.ConfigParser(
            inline_comment_prefixes=(";", "#"),
            interpolation=None,   # '%' in Pfaden soll nicht interpretiert werden
        )
        self._read()
        self._load_values()

    # -- Einlesen ----------------------------------------------------------

    def _read(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                self.parser.read_file(fh)
        except FileNotFoundError:
            raise ConfigError(f"Konfigurationsdatei nicht gefunden: {self.path}")
        except UnicodeDecodeError:
            raise ConfigError(
                f"{self.path.name} ist nicht UTF-8-kodiert. "
                "Bitte im Editor als UTF-8 speichern."
            )
        except configparser.Error as exc:
            raise ConfigError(f"{self.path.name} ist fehlerhaft:\n     {exc}")

    # -- Typisierte Einzelwerte -------------------------------------------

    def _raw(self, section: str, key: str, default: Optional[str] = None) -> str:
        if not self.parser.has_section(section):
            if default is not None:
                return default
            raise ConfigError(f"Abschnitt [{section}] fehlt in {self.path.name}")
        if not self.parser.has_option(section, key):
            if default is not None:
                return default
            raise ConfigError(
                f"Eintrag '{key}' fehlt im Abschnitt [{section}] von {self.path.name}"
            )
        return self.parser.get(section, key).strip()

    def text(self, section: str, key: str, default: Optional[str] = None) -> str:
        return self._raw(section, key, default)

    def flag(self, section: str, key: str, default: bool) -> bool:
        raw = self._raw(section, key, "").strip().lower()
        if not raw:
            return default
        if raw in self.BOOL_TRUE:
            return True
        if raw in self.BOOL_FALSE:
            return False
        raise ConfigError(
            f"[{section}] {key} = '{raw}' ist kein Ja/Nein-Wert. "
            "Erlaubt: true/false (auch ja/nein, an/aus)."
        )

    def number(self, section: str, key: str, default: int,
               minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
        raw = self._raw(section, key, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            raise ConfigError(f"[{section}] {key} = '{raw}' ist keine ganze Zahl.")
        if minimum is not None and value < minimum:
            raise ConfigError(f"[{section}] {key} = {value} ist kleiner als {minimum}.")
        if maximum is not None and value > maximum:
            raise ConfigError(f"[{section}] {key} = {value} ist groesser als {maximum}.")
        return value

    def items(self, section: str, key: str, default: str = "") -> List[str]:
        raw = self._raw(section, key, default)
        return [part.strip() for part in raw.split(",") if part.strip()]

    # -- Werte uebernehmen -------------------------------------------------

    def _load_values(self) -> None:
        # --- YouTube ---
        self.yt_client_secrets = self.text("YouTube", "client_secrets_file")
        self.yt_token_file = self.text("YouTube", "token_file")
        self.yt_playlist_id = self.text("YouTube", "playlist_id", "")
        self.yt_privacy = self.text("YouTube", "privacy_status", "private").lower()
        self.yt_tags = self.items("YouTube", "tags", "Zeitraffer, GoPro")
        self.yt_category_id = self.text("YouTube", "category_id", "19")
        self.yt_public_stats = self.flag("YouTube", "public_stats_viewable", True)
        self.yt_embeddable = self.flag("YouTube", "embeddable", True)
        self.yt_license = self.text("YouTube", "license", "youtube")
        self.yt_made_for_kids = self.flag("YouTube", "made_for_kids", False)
        self.yt_synthetic = self.flag("YouTube", "contains_synthetic_media", False)

        # --- Verzeichnisse ---
        # Leere Werte relativ zum Skriptverzeichnis, nicht zum aktuellen
        # Arbeitsverzeichnis - sonst schlaegt der Start per Doppelklick fehl.
        base_raw = self.text("Verzeichnisse", "basis_dir", "")
        self.base_dir = Path(base_raw).expanduser() if base_raw else SCRIPT_DIR

        def resolve(key: str, fallback: str) -> Path:
            raw = self.text("Verzeichnisse", key, "")
            return Path(raw).expanduser() if raw else self.base_dir / fallback

        self.aufnahmen_dir = resolve("aufnahmen_dir", "aufnahmen")
        self.output_dir = resolve("output_dir", "output")
        self.archiv_dir = resolve("archiv_dir", "archiv")
        self.log_dir = resolve("log_dir", "logs")
        self.temp_dir = resolve("temp_dir", "temp")
        self.beschreibung_dir = resolve("beschreibung_dir", "beschreibungen")

        # --- Render ---
        self.encoder = self.text("Render", "encoder", "auto") or "auto"
        self.qualitaet = normalize_key(self.text("Render", "qualitaet", "hoch"))
        self.tempo = normalize_key(self.text("Render", "tempo", "schnell"))
        self.ziel_fps = self.number("Render", "ziel_fps", 0, minimum=0, maximum=240)
        self.ziel_fps_merken = self.flag("Render", "ziel_fps_merken", True)

        # --- Ablauf ---
        self.testrender_dauer = self.number("Ablauf", "testrender_dauer", 20, 1, 300)
        self.erste_vorschau_dauer = self.number("Ablauf", "erste_vorschau_dauer", 20, 1, 600)
        self.temp_auto_cleanup = self.flag("Ablauf", "temp_auto_cleanup", True)
        self.archiv_versuche = self.number("Ablauf", "archiv_versuche", 6, 1, 100)
        self.archiv_wartezeit = self.number("Ablauf", "archiv_wartezeit", 10, 0, 600)
        self.materiallaenge_in_liste = self.flag("Ablauf", "materiallaenge_in_liste", True)

        # --- Anzeige ---
        self.anzeige_farben = self.flag("Anzeige", "farben", True)
        self.anzeige_symbole = self.flag("Anzeige", "symbole", True)
        self.anzeige_ausfuehrlich = self.flag("Anzeige", "ausfuehrlich", False)
        self.anzeige_breite = self.number("Anzeige", "breite", 78, 40, 200)

    # -- Pruefung ----------------------------------------------------------

    def validate(self) -> List[str]:
        """Prueft die Werte auf Plausibilitaet. Gibt Warnungen zurueck.

        Harte Fehler beenden das Programm sofort - besser jetzt als nach
        Stunden Renderzeit beim Upload.
        """
        errors: List[str] = []
        warnings: List[str] = []

        if self.yt_privacy not in VALID_PRIVACY:
            errors.append(
                f"[YouTube] privacy_status = '{self.yt_privacy}' ist ungueltig. "
                f"Erlaubt: {', '.join(VALID_PRIVACY)}"
            )
        if self.yt_license not in VALID_LICENSE:
            errors.append(
                f"[YouTube] license = '{self.yt_license}' ist ungueltig. "
                f"Erlaubt: {', '.join(VALID_LICENSE)}"
            )
        if not str(self.yt_category_id).isdigit():
            errors.append(
                f"[YouTube] category_id = '{self.yt_category_id}' muss eine Zahl sein."
            )
        if not self.yt_tags:
            warnings.append("[YouTube] tags ist leer - es werden keine Standard-Tags gesetzt.")

        if self.qualitaet not in QUALITY_LEVELS:
            warnings.append(
                f"[Render] qualitaet = '{self.qualitaet}' ist unbekannt "
                f"(erlaubt: {', '.join(QUALITY_LEVELS)}) - verwende 'hoch'."
            )
            self.qualitaet = "hoch"
        if self.tempo not in SPEED_LEVELS:
            warnings.append(
                f"[Render] tempo = '{self.tempo}' ist unbekannt "
                "(erlaubt: sehr schnell, schnell, ausgewogen, langsam) - verwende 'schnell'."
            )
            self.tempo = "schnell"

        known = ["auto"] + list(ENCODER_PROFILES.keys())
        if self.encoder not in known:
            warnings.append(
                f"[Render] encoder = '{self.encoder}' ist dem Skript nicht bekannt. "
                "Er wird getestet; bei Misserfolg wird libx264 verwendet."
            )

        if errors:
            ui.plain()
            ui.error(f"Fehler in {self.path.name}:")
            for err in errors:
                ui.plain(f"   - {err}")
            ui.plain()
            ui.plain("   Bitte korrigieren und das Skript erneut starten.")
            sys.exit(1)

        return warnings

    # -- Zurueckschreiben --------------------------------------------------

    def save_ziel_fps(self, fps: int, logger: Optional["Logger"] = None) -> bool:
        """Schreibt die zuletzt verwendete Ziel-FPS in die INI zurueck.

        Bewusst KEIN configparser.write(): das wuerde die Datei komplett neu
        erzeugen und dabei saemtliche Kommentare verwerfen - bei dieser
        Config waere das ein erheblicher Verlust, da dort die gesamte
        Dokumentation steckt.

        Stattdessen wird gezielt die eine Zeile 'ziel_fps = ...' im Abschnitt
        [Render] ersetzt. Vor dem Schreiben entsteht eine .bak-Sicherung,
        geschrieben wird ueber eine temporaere Datei mit anschliessendem
        os.replace (atomar), damit ein Abbruch die Config nie halbfertig
        zuruecklaesst.
        """
        if not self.ziel_fps_merken:
            return False
        if fps == self.ziel_fps:
            return False   # unveraendert - kein Schreibzugriff noetig

        try:
            original = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            if logger:
                logger.log(f"Config zum Aktualisieren nicht lesbar: {exc}", "WARNING")
            return False

        lines = original.splitlines(keepends=True)
        in_render = False
        replaced = False

        for index, line in enumerate(lines):
            stripped = line.strip()

            if stripped.startswith("[") and stripped.endswith("]"):
                in_render = stripped.lower() == "[render]"
                continue

            if not in_render or not stripped or stripped[0] in ";#":
                continue

            # 'ziel_fps' treffen, aber NICHT 'ziel_fps_merken'
            match = re.match(r"^(\s*)ziel_fps(\s*)([:=])(\s*)(.*?)(\r?\n?)$", line)
            if match:
                indent, pre, sep, post, _old, eol = match.groups()
                lines[index] = f"{indent}ziel_fps{pre}{sep}{post}{fps}{eol or os.linesep}"
                replaced = True
                break

        if not replaced:
            if logger:
                logger.log(
                    "Eintrag 'ziel_fps' im Abschnitt [Render] nicht gefunden - "
                    "Wert wurde nicht gespeichert", "WARNING"
                )
            ui.warn(f"Ziel-FPS konnte nicht in {self.path.name} gespeichert werden "
                    "(Eintrag 'ziel_fps' im Abschnitt [Render] nicht gefunden).")
            return False

        backup = self.path.with_suffix(self.path.suffix + ".bak")
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")

        try:
            shutil.copy2(self.path, backup)
            temporary.write_text("".join(lines), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            if logger:
                logger.log(f"Ziel-FPS konnte nicht gespeichert werden: {exc}", "WARNING")
            ui.warn(f"Ziel-FPS konnte nicht gespeichert werden: {exc}")
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return False

        self.ziel_fps = fps
        if logger:
            logger.log(f"Ziel-FPS {fps} in {self.path.name} gespeichert "
                       f"(Sicherung: {backup.name})")
        return True


# ============================================================================
# Migration der alten gopro_config.py
# ============================================================================

INI_TEMPLATE = """; ============================================================================
; GoPro Time-Lapse Vibe-Coding Processor - Konfiguration
; Automatisch erzeugt am {stamp} aus gopro_config.py
;
; Diese Datei ist eine klassische INI-Datei (kein Python-Code mehr).
; Kommentarzeilen beginnen mit ';' - Werte OHNE Anfuehrungszeichen schreiben.
; Ein '%' in einem Pfad muss verdoppelt werden (%%).
; ============================================================================


[YouTube]
client_secrets_file = {client_secrets}
token_file          = {token}
playlist_id         = {playlist}

; Sichtbarkeit: public | private | unlisted
privacy_status      = {privacy}

; Standard-Tags (Komma-getrennt)
tags                = {tags}

; 19 = Travel & Events, 22 = People & Blogs, 28 = Science & Technology
category_id         = {category}

public_stats_viewable    = {public_stats}
embeddable               = {embeddable}

; Lizenz: youtube | creativeCommon
license                  = {license}
made_for_kids            = {kids}
contains_synthetic_media = {synthetic}


[Verzeichnisse]
; Leere Werte werden relativ zu basis_dir aufgeloest.
; Leeres basis_dir = Verzeichnis dieses Skripts.
basis_dir        = {base}
aufnahmen_dir    = {aufnahmen}
output_dir       = {output}
archiv_dir       = {archiv}
log_dir          = {logs}
temp_dir         = {temp}
beschreibung_dir = {beschreibung}


[Render]
; encoder:   auto | libx264 | h264_qsv | h264_nvenc | h264_amf
; qualitaet: niedrig | mittel | hoch | maximal
; tempo:     sehr schnell | schnell | ausgewogen | langsam
encoder   = {encoder}
qualitaet = {qualitaet}
tempo     = {tempo}

; Ziel-Framerate. WIRD VOM SKRIPT AUTOMATISCH AKTUALISIERT.
; 0 = keine Vorbelegung.
ziel_fps  = {ziel_fps}
ziel_fps_merken = true


[Ablauf]
testrender_dauer        = {testrender}
erste_vorschau_dauer    = {vorschau}
temp_auto_cleanup       = {cleanup}
archiv_versuche         = {versuche}
archiv_wartezeit        = {wartezeit}
materiallaenge_in_liste = {material}


[Anzeige]
farben       = true
symbole      = true
ausfuehrlich = false
breite       = 78
"""


def _as_ini_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def migrate_legacy_config(py_path: Path, ini_path: Path) -> bool:
    """Erzeugt gopro_config.ini aus einer vorhandenen gopro_config.py."""
    ui.header("Konfiguration wird migriert", "box")
    ui.plain(f"Gefunden: {py_path.name}")
    ui.plain(f"Erzeuge:  {ini_path.name}")
    ui.plain()

    import importlib.util
    spec = importlib.util.spec_from_file_location("gopro_config_legacy", py_path)
    if spec is None or spec.loader is None:
        ui.error(f"{py_path.name} konnte nicht gelesen werden.")
        return False

    legacy = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(legacy)
    except Exception as exc:
        ui.error(f"{py_path.name} enthaelt einen Fehler und kann nicht gelesen werden:")
        ui.plain(f"   {exc}")
        return False

    def get(name: str, default: Any = "") -> Any:
        return getattr(legacy, name, default)

    tags = get("YOUTUBE_TAGS", ["Zeitraffer", "GoPro"])
    if isinstance(tags, (list, tuple)):
        tags = ", ".join(str(t) for t in tags)

    content = INI_TEMPLATE.format(
        stamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        client_secrets=get("YOUTUBE_CLIENT_SECRETS_FILE", ""),
        token=get("YOUTUBE_TOKEN_FILE", ""),
        playlist=get("YOUTUBE_PLAYLIST_ID", ""),
        privacy=get("YOUTUBE_PRIVACY_STATUS", "private"),
        tags=tags,
        category=get("YOUTUBE_CATEGORY_ID", "19"),
        public_stats=_as_ini_bool(get("YOUTUBE_PUBLIC_STATS_VIEWABLE", True)),
        embeddable=_as_ini_bool(get("YOUTUBE_EMBEDDABLE", True)),
        license=get("YOUTUBE_LICENSE", "youtube"),
        kids=_as_ini_bool(get("YOUTUBE_MADE_FOR_KIDS", False)),
        synthetic=_as_ini_bool(get("YOUTUBE_CONTAINS_SYNTHETIC_MEDIA", False)),
        base=get("BASE_DIR", ""),
        aufnahmen=get("AUFNAHMEN_DIR", ""),
        output=get("OUTPUT_DIR", ""),
        archiv=get("ARCHIVE_DIR", ""),
        logs=get("LOG_DIR", ""),
        temp=get("TEMP_DIR", ""),
        beschreibung=get("BESCHREIBUNG_DIR", ""),
        encoder=get("FFMPEG_ENCODER", "auto") or "auto",
        qualitaet=get("FFMPEG_QUALITY", "hoch") or "hoch",
        tempo=get("FFMPEG_SPEED", "schnell") or "schnell",
        ziel_fps=0,
        testrender=get("DEFAULT_TEST_PREVIEW_DURATION", 20),
        vorschau=get("FIRST_PREVIEW_DURATION", 20),
        cleanup=_as_ini_bool(get("TEMP_AUTO_CLEANUP", True)),
        versuche=get("ARCHIVE_MAX_ATTEMPTS", 6),
        wartezeit=get("ARCHIVE_RETRY_DELAY", 10),
        material=_as_ini_bool(get("SHOW_MATERIAL_LENGTH_IN_LIST", True)),
    )

    try:
        ini_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        ui.error(f"{ini_path.name} konnte nicht geschrieben werden: {exc}")
        return False

    ui.ok(f"{ini_path.name} wurde erstellt.")
    ui.detail(f"Die alte {py_path.name} bleibt unveraendert liegen.")
    ui.plain()
    return True


def load_configuration() -> Config:
    """Laedt die Konfiguration, migriert bei Bedarf und prueft sie."""
    if not CONFIG_INI.exists():
        if CONFIG_PY_LEGACY.exists():
            if not migrate_legacy_config(CONFIG_PY_LEGACY, CONFIG_INI):
                sys.exit(1)
        else:
            ui.error("Keine Konfiguration gefunden!")
            ui.plain(f"   Erwartet: {CONFIG_INI}")
            ui.plain("   Bitte gopro_config.ini neben dem Skript anlegen.")
            sys.exit(1)

    try:
        config = Config(CONFIG_INI)
    except ConfigError as exc:
        ui.error(str(exc))
        sys.exit(1)

    ui.configure(
        width=config.anzeige_breite,
        color=config.anzeige_farben,
        symbols=config.anzeige_symbole,
        verbose=config.anzeige_ausfuehrlich,
    )

    for warning in config.validate():
        ui.warn(warning)

    return config


# ============================================================================
# Encoder-Profile
# ============================================================================
#
# Jeder Encoder bringt sein eigenes Vokabular mit:
#   libx264           : -preset <name>,  Qualitaet ueber -crf (kleiner = besser)
#   h264_nvenc        : -preset <name>,  Qualitaet ueber -rc vbr -cq
#   h264_qsv          : -preset <name>,  Qualitaet ueber -global_quality
#   h264_amf          : -quality <name>  (NICHT -preset!), Qualitaet ueber -rc cqp
#   h264_videotoolbox : keine Stufen,    Qualitaet ueber -q:v (groesser = besser)
#
# Die Konfiguration kennt davon nichts - sie waehlt nur "hoch"/"schnell".
# ============================================================================

QUALITY_LEVELS = ("niedrig", "mittel", "hoch", "maximal")
SPEED_LEVELS = ("sehr_schnell", "schnell", "ausgewogen", "langsam")

ENCODER_PROFILES: Dict[str, Dict[str, Any]] = {
    "libx264": {
        "label": "libx264 (Software/CPU)",
        "speed_flag": "-preset",
        "speed": {"sehr_schnell": "veryfast", "schnell": "fast",
                  "ausgewogen": "medium", "langsam": "slow"},
        "quality": {"niedrig": ["-crf", "26"], "mittel": ["-crf", "23"],
                    "hoch": ["-crf", "20"], "maximal": ["-crf", "17"]},
    },
    "h264_nvenc": {
        "label": "h264_nvenc (NVIDIA)",
        "speed_flag": "-preset",
        "speed": {"sehr_schnell": "fast", "schnell": "fast",
                  "ausgewogen": "medium", "langsam": "slow"},
        "quality": {
            "niedrig": ["-rc", "vbr", "-cq", "30", "-b:v", "0"],
            "mittel": ["-rc", "vbr", "-cq", "26", "-b:v", "0"],
            "hoch": ["-rc", "vbr", "-cq", "22", "-b:v", "0"],
            "maximal": ["-rc", "vbr", "-cq", "18", "-b:v", "0"],
        },
    },
    "h264_qsv": {
        "label": "h264_qsv (Intel Quick Sync)",
        "speed_flag": "-preset",
        "speed": {"sehr_schnell": "veryfast", "schnell": "fast",
                  "ausgewogen": "medium", "langsam": "slow"},
        "quality": {"niedrig": ["-global_quality", "30"],
                    "mittel": ["-global_quality", "26"],
                    "hoch": ["-global_quality", "22"],
                    "maximal": ["-global_quality", "18"]},
    },
    "h264_amf": {
        "label": "h264_amf (AMD)",
        "speed_flag": "-quality",   # heisst NICHT -preset
        "speed": {"sehr_schnell": "speed", "schnell": "speed",
                  "ausgewogen": "balanced", "langsam": "quality"},
        "quality": {
            "niedrig": ["-rc", "cqp", "-qp_i", "30", "-qp_p", "32"],
            "mittel": ["-rc", "cqp", "-qp_i", "26", "-qp_p", "28"],
            "hoch": ["-rc", "cqp", "-qp_i", "22", "-qp_p", "24"],
            "maximal": ["-rc", "cqp", "-qp_i", "18", "-qp_p", "20"],
        },
    },
    "h264_videotoolbox": {
        "label": "h264_videotoolbox (Apple)",
        "speed_flag": None,
        "speed": {},
        # Skala invers: groesser = besser
        "quality": {"niedrig": ["-q:v", "40"], "mittel": ["-q:v", "55"],
                    "hoch": ["-q:v", "65"], "maximal": ["-q:v", "80"]},
    },
}


def get_encoder_profile(encoder: str) -> Dict[str, Any]:
    """Liefert das Profil eines Encoders, mit libx264 als sicherem Fallback."""
    return ENCODER_PROFILES.get(encoder, ENCODER_PROFILES["libx264"])


# ============================================================================
# GoPro-Dateinamen und Sortierung
# ============================================================================

def parse_gopro_name(stem: str) -> Optional[Tuple[int, int]]:
    """Zerlegt einen GoPro-Dateinamen in (Videonummer, Chapter-Nummer).

    Erkennt beide Schemata der Hero 5: 'GOPR1290' als Chapter 0 und
    'GP011290' als Chapter 1.
    """
    match = GOPRO_FIRST_RE.match(stem)
    if match:
        return int(match.group(2)), 0
    match = GOPRO_CHAPTER_RE.match(stem)
    if match:
        return int(match.group(3)), int(match.group(2))
    return None


def sort_gopro_files(files: List[Path]) -> Tuple[List[Path], bool]:
    """Sortiert GoPro-Dateien in korrekter zeitlicher Reihenfolge.

    Primaer nach Namensschema (Videonummer, dann Chapter). Nur wenn nicht
    alle Dateien einem bekannten Schema folgen, wird auf die Sortierung nach
    Datei-Zeitstempel zurueckgefallen - die ist unzuverlaessig, sobald die
    Dateien mit einem Werkzeug kopiert wurden, das mtime nicht erhaelt.
    Der zweite Rueckgabewert signalisiert diesen Fallback.
    """
    if not files:
        return [], True

    parsed = []
    for f in files:
        key = parse_gopro_name(f.stem)
        if key is None:
            return sorted(files, key=lambda p: p.stat().st_mtime), False
        parsed.append((key[0], key[1], f))

    parsed.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in parsed], True


def validate_youtube_metadata(title: str, description: str, tags: List[str]) -> List[str]:
    """Prueft die YouTube-Metadaten gegen die API-Limits."""
    problems: List[str] = []

    if not title.strip():
        problems.append("Der Titel ist leer.")
    elif len(title) > YT_MAX_TITLE_LEN:
        problems.append(f"Titel ist {len(title)} Zeichen lang, "
                        f"erlaubt sind max. {YT_MAX_TITLE_LEN}.")
    if "<" in title or ">" in title:
        problems.append("Titel enthaelt '<' oder '>' - das lehnt die YouTube-API ab.")

    if len(description) > YT_MAX_DESCRIPTION_LEN:
        problems.append(f"Beschreibung ist {len(description)} Zeichen lang, "
                        f"erlaubt sind max. {YT_MAX_DESCRIPTION_LEN}.")
    if "<" in description or ">" in description:
        problems.append("Beschreibung enthaelt '<' oder '>' - das lehnt die YouTube-API ab.")

    tags_total = sum(len(t) for t in tags) + max(0, len(tags) - 1)
    if tags_total > YT_MAX_TAGS_TOTAL_LEN:
        problems.append(f"Tags sind zusammen {tags_total} Zeichen lang, "
                        f"erlaubt sind max. {YT_MAX_TAGS_TOTAL_LEN}.")

    return problems


# ============================================================================
# Logger
# ============================================================================

class Logger:
    """Schreibt die Logdatei und gibt bei Bedarf auf der Konsole aus.

    Die Logdatei enthaelt IMMER alles. Auf der Konsole erscheint eine
    Logzeile nur, wenn console=True gesetzt ist oder in der INI
    ausfuehrlich=true steht.
    """

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.warnings: List[str] = []
        self.errors: List[str] = []

    def log(self, message: str, level: str = "INFO", console: bool = False) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"{timestamp} - {level} - {message}"

        if level == "WARNING":
            self.warnings.append(message)
        elif level == "ERROR":
            self.errors.append(message)

        if console or ui.verbose:
            if level == "WARNING":
                ui.warn(message)
            elif level == "ERROR":
                ui.error(message)
            else:
                ui.plain(entry if ui.verbose else f"   {message}")

        try:
            with open(self.log_file, 'a', encoding='utf-8') as fh:
                fh.write(entry + "\n")
        except OSError as exc:
            ui.warn(f"Logdatei nicht schreibbar ({exc})")

    def error_and_exit(self, message: str) -> None:
        self.log(message, "ERROR")
        ui.plain()
        ui.error(message)
        ui.detail(f"Details in der Logdatei: {self.log_file}")
        sys.exit(1)


# ============================================================================
# FFmpeg-Handler
# ============================================================================

class FFmpegHandler:
    """Alle FFmpeg- und ffprobe-Operationen."""

    def __init__(self, logger: Logger, config: Config, detect_encoder: bool = True):
        """
        detect_encoder=False ueberspringt die Encoder-Erkennung.

        Der Uploadmodus (-u) rendert nicht und braucht deshalb keinen
        Encoder. Die Erkennung kostet mehrere Sekunden Testencodes - das
        waere dort verschenkte Zeit. ffprobe-Abfragen (Dauer, Aufnahmedatum)
        funktionieren unabhaengig davon.
        """
        self.logger = logger
        self.cfg = config
        self.cpu_count = os.cpu_count() or 4
        self.encoder = "libx264"
        self.profile = get_encoder_profile("libx264")
        self.quality_args: List[str] = []
        self.speed_args: List[str] = []
        self._duration_cache: Dict[str, float] = {}

        if detect_encoder:
            self.logger.log(f"CPU-Kerne erkannt: {self.cpu_count}")
            self._resolve_encoder()
        else:
            self.logger.log("Encoder-Erkennung uebersprungen (Uploadmodus)")

    # -- Encoder -----------------------------------------------------------

    def _build_encoder_args(self, encoder: str) -> Tuple[List[str], List[str], Optional[str]]:
        """Uebersetzt die abstrakte Konfiguration in FFmpeg-Parameter.

        Statt einen Preset-Namen blind durchzureichen, wird pro Encoder
        nachgeschlagen, ob er eine Geschwindigkeitsstufe kennt und wie der
        Parameter heisst. Zusaetzlich wird IMMER ein Qualitaetsparameter
        gesetzt - ohne ihn rendern Hardware-Encoder mit ihrer sehr niedrigen
        Standardbitrate.
        """
        profile = get_encoder_profile(encoder)
        note: Optional[str] = None

        quality_args = list(profile["quality"].get(self.cfg.qualitaet, []))
        speed_args: List[str] = []
        speed_flag = profile.get("speed_flag")

        if speed_flag is None:
            if self.cfg.tempo != "schnell":
                note = (f"{profile['label']} kennt keine Geschwindigkeitsstufen - "
                        "die Einstellung 'tempo' wird ignoriert.")
        else:
            speed_value = profile["speed"].get(self.cfg.tempo)
            if speed_value:
                speed_args = [speed_flag, speed_value]

        return quality_args, speed_args, note

    def _probe_encoder_works(self, encoder_name: str) -> bool:
        """Mini-Testencode mit EXAKT den spaeter verwendeten Parametern."""
        null_output = "NUL" if sys.platform == "win32" else "/dev/null"
        quality_args, speed_args, _ = self._build_encoder_args(encoder_name)

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=5",
               "-frames:v", "5", "-c:v", encoder_name]
        cmd.extend(quality_args)
        cmd.extend(speed_args)
        cmd.extend(["-pix_fmt", "yuv420p", "-f", "null", null_output])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _auto_detect_encoder(self) -> str:
        """Probiert die Hardware-Encoder durch und nimmt den ersten nutzbaren."""
        ui.plain(f"{ui.sym('search')} Suche Hardware-Beschleunigung "
                 f"(einmaliger Test beim Start)...")
        for candidate in ["h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"]:
            works = self._probe_encoder_works(candidate)
            mark = ui.sym('ok') if works else "  -"
            ui.plain(f"   {mark} {candidate:<22} "
                     f"{'verfuegbar' if works else 'nicht nutzbar'}")
            self.logger.log(f"Encoder-Test '{candidate}': "
                            f"{'erfolgreich' if works else 'fehlgeschlagen'}")
            if works:
                return candidate

        ui.detail("Keine Hardware-Beschleunigung nutzbar - verwende libx264 (Software).")
        self.logger.log("Keine Hardware-Beschleunigung gefunden, Fallback auf libx264")
        return "libx264"

    def _resolve_encoder(self) -> None:
        """Ermittelt Encoder und die konkreten FFmpeg-Parameter."""
        desired = self.cfg.encoder

        if desired == "auto":
            encoder = self._auto_detect_encoder()
        elif desired == "libx264":
            encoder = desired
        else:
            ui.plain(f"{ui.sym('search')} Pruefe konfigurierten Encoder '{desired}'...")
            if self._probe_encoder_works(desired):
                encoder = desired
                self.logger.log(f"Konfigurierter Encoder '{desired}' verifiziert")
            else:
                ui.warn(f"Encoder '{desired}' funktioniert auf diesem System nicht "
                        "- verwende libx264 (Software).")
                self.logger.log(f"Encoder '{desired}' nicht nutzbar, Fallback libx264", "WARNING")
                encoder = "libx264"

        self.encoder = encoder
        self.profile = get_encoder_profile(encoder)
        self.quality_args, self.speed_args, note = self._build_encoder_args(encoder)

        if note:
            ui.info(note)
            self.logger.log(f"Encoder-Hinweis: {note}", "WARNING")

        quality_text = " ".join(self.quality_args) or "(Standard)"
        speed_text = " ".join(self.speed_args) or "(keine Stufe)"
        ui.ok(f"Encoder: {self.profile['label']}  |  Qualitaet: {self.cfg.qualitaet}"
              f"  |  Tempo: {self.cfg.tempo}")
        self.logger.log(f"Encoder-Profil aktiv: {encoder} | Qualitaet={self.cfg.qualitaet} "
                        f"{quality_text} | Tempo={self.cfg.tempo} {speed_text}")

    # -- Dateilisten -------------------------------------------------------

    def get_file_list(self, folder: str, limit_files: int = None,
                      file_pattern: str = "*.MP4") -> List[Path]:
        """Findet Medien-Dateien im Ordner und sortiert sie korrekt."""
        folder_path = Path(folder)
        if not folder_path.exists():
            self.logger.error_and_exit(f"Ordner existiert nicht: {folder}")

        files = list(folder_path.glob(file_pattern))
        if not files:
            self.logger.error_and_exit(f"Keine Dateien ({file_pattern}) in: {folder}")

        files, used_scheme = sort_gopro_files(files)
        if not used_scheme:
            ui.warn("Nicht alle Dateien folgen dem GoPro-Namensschema - es wird nach "
                    "Datei-Zeitstempel sortiert.")
            ui.detail("Bitte die Reihenfolge im Ergebnis pruefen.")
            self.logger.log("Sortierung per Datei-Zeitstempel (Fallback) - "
                            "Reihenfolge koennte falsch sein", "WARNING")
        else:
            self.logger.log("Sortierung nach GoPro-Namensschema (Videonummer, Chapter)")

        if limit_files:
            files = files[:limit_files]

        self.logger.log(f"{len(files)} Dateien ({file_pattern}) gefunden")
        return files

    # -- Render ------------------------------------------------------------

    def render_from_files(self, files: List[Path], output: str, factor: float,
                          fps: int, expected_output: float) -> float:
        """Fuegt alle Quelldateien zusammen und rendert in EINEM Durchgang.

        NEU in v2.4.0. Ersetzt den bisherigen Zweischritt (verlustfreier
        Concat nach combined.mp4, danach Render). Gruende:

        1. Die Zwischendatei war ueberfluessig - danach wurde ohnehin neu
           encodiert (setpts, neue FPS, neuer Encoder).
        2. Sie war die EINZIGE Stelle, an der stillschweigend Material
           verschwinden konnte: FFmpegs Stream-Copy-Concat brach bei
           GoPro-Containern vorzeitig ab und meldete trotzdem Exit-Code 0.
           Im Ordner 2026-09-25 gingen so 550 von 744 Sekunden verloren.
        3. Sie kostete Schreiblast in Groesse des gesamten Quellmaterials
           (6-9 GB je Lauf).

        Der concat-FILTER dekodiert jede Datei einzeln und normalisiert sie
        vor dem Aneinanderhaengen - er kann strukturell nichts verlieren.

        '-an': Zeitraffer hat keinen Ton. Ohne dieses Flag wuerde FFmpeg eine
        vorhandene Tonspur mitnehmen und neu codieren, aber NICHT zeitraffen
        (setpts wirkt nur auf Video).

        Rueckgabe: Renderzeit in Sekunden.
        """
        if not files:
            self.logger.error_and_exit("Keine Quelldateien zum Rendern.")

        # Zielaufloesung = erste Datei. Eine Aufnahme ist pro Ordner
        # einheitlich; abweichende Chapter werden gemeldet und eingepasst.
        size = self.get_video_size(str(files[0]))
        if size is None:
            self.logger.error_and_exit(
                f"Aufloesung von {files[0].name} nicht ermittelbar.")
        width, height = size

        for f in files[1:]:
            other = self.get_video_size(str(f))
            if other and other != size:
                ui.warn(f"{f.name} hat {other[0]}x{other[1]} statt "
                        f"{width}x{height} - wird eingepasst.")
                self.logger.log(f"Abweichende Aufloesung {f.name}: {other}", "WARNING")

        ui.plain(f"   {len(files)} Dateien  |  {width}x{height}  ->  "
                 f"Ergebnis {format_material_len(expected_output)}   "
                 f"(Faktor {factor}, {fps} FPS)")
        ui.detail(f"Encoder: {self.profile['label']}, "
                  f"Qualitaet {self.cfg.qualitaet}, {self.cpu_count} CPU-Kerne")

        cmd = ["ffmpeg", "-y", "-fflags", "+genpts"]
        for f in files:
            cmd += ["-i", str(f)]

        chain = ""
        for i in range(len(files)):
            chain += (f"[{i}:v]scale={width}:{height}:"
                      f"force_original_aspect_ratio=decrease,"
                      f"pad={width}:{height}:-1:-1,setsar=1,format=yuv420p[v{i}];")
        chain += "".join(f"[v{i}]" for i in range(len(files)))
        chain += f"concat=n={len(files)}:v=1:a=0[cat];[cat]setpts=PTS/{factor}[out]"

        cmd += ["-filter_complex", chain, "-map", "[out]", "-an",
                "-r", str(fps), "-threads", "0", "-c:v", self.encoder]
        cmd += self.quality_args
        cmd += self.speed_args
        cmd += ["-pix_fmt", "yuv420p", "-stats", "-progress", "pipe:1", output]

        self.logger.log(f"Ein-Pass-Render: {len(files)} Dateien, Faktor {factor}, "
                        f"{fps} fps, {width}x{height}, Encoder {self.encoder}, "
                        f"Qualitaet {self.cfg.qualitaet}, Tempo {self.cfg.tempo}")

        return self._run_with_progress(cmd, expected_output, output)

    def adjust_speed_with_progress(self, input_file: str, output: str, factor: float,
                                   fps: int = 60, duration: Optional[float] = None,
                                   is_test: bool = False) -> float:
        """Rendert EINE Datei mit Zeitraffer-Faktor (Testrender/Vorschau).

        Seit v2.4.0 nur noch fuer den Testrender aus einer einzelnen Datei
        verwendet; der Finalrender laeuft ueber render_from_files().

        Rueckgabe: benoetigte Renderzeit in Sekunden.
        """
        total_duration = self.get_duration(input_file)

        if duration:
            expected_output = float(duration)
        elif total_duration:
            expected_output = total_duration / factor
        else:
            expected_output = 0.0

        if total_duration:
            if is_test:
                ui.plain(f"   Quelle {total_duration:.0f}s  ->  Vorschau "
                         f"{expected_output:.0f}s   (Faktor {factor})")
            else:
                ui.plain(f"   Videomaterial {format_material_len(total_duration)}  ->  "
                         f"Ergebnis {format_material_len(expected_output)}   "
                         f"(Faktor {factor}, {fps} FPS)")
                ui.detail(f"Encoder: {self.profile['label']}, "
                          f"Qualitaet {self.cfg.qualitaet}, {self.cpu_count} CPU-Kerne")

        cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", input_file,
               "-threads", "0", "-an",
               "-filter:v", f"setpts=PTS/{factor}", "-r", str(fps),
               "-c:v", self.encoder]
        cmd.extend(self.quality_args)
        cmd.extend(self.speed_args)
        cmd.extend(["-pix_fmt", "yuv420p", "-stats", "-progress", "pipe:1"])
        if duration:
            cmd.extend(["-t", str(duration)])
        cmd.append(output)

        self.logger.log(f"Render: Faktor {factor}, {fps} fps, Encoder {self.encoder}, "
                        f"Qualitaet {self.cfg.qualitaet}, Tempo {self.cfg.tempo}")

        return self._run_with_progress(cmd, expected_output, output)

    def _run_with_progress(self, cmd: List[str], expected_output: float,
                           output: str) -> float:
        """Fuehrt einen FFmpeg-Renderlauf mit Fortschrittsbalken aus.

        Seit v2.4.0 von adjust_speed_with_progress() und render_from_files()
        gemeinsam genutzt - vorher lag die Logik nur in der ersten Methode.
        """
        start_time = time.time()
        stderr_tail: List[str] = []

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, bufsize=1)
            print_lock = threading.Lock()

            def read_stderr():
                """Liest stderr mit, damit der Puffer nicht volllaeuft."""
                for line in process.stderr:
                    line = line.strip()
                    if not line:
                        continue
                    stderr_tail.append(line)
                    if len(stderr_tail) > 40:
                        del stderr_tail[0]
                    if "error" in line.lower() or "invalid" in line.lower():
                        with print_lock:
                            # Balkenzeile abschliessen, sonst bleibt ein Rest stehen.
                            ui.clear_line()
                            ui.warn(line)

            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stderr_thread.start()

            for line in process.stdout:
                line = line.strip()

                if line.startswith("out_time="):
                    time_str = line.split("=")[1]
                    if time_str == "N/A":
                        continue
                    parts = time_str.split(":")
                    if len(parts) != 3:
                        continue
                    try:
                        current = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                    except ValueError:
                        continue

                    elapsed = time.time() - start_time
                    if expected_output > 0:
                        percent = min(100, int((current / expected_output) * 100))
                        eta = ""
                        if percent > 0:
                            remaining = max(0.0, elapsed / (percent / 100) - elapsed)
                            eta = f" | noch ca. {format_hms(remaining)}"
                        bar = ui.progress_bar(percent)
                        with print_lock:
                            print(f"\r   [{bar}] {percent:3}%  "
                                  f"{format_hms(elapsed)}{eta}   ", end="", flush=True)
                    else:
                        with print_lock:
                            print(f"\r   laeuft... {format_hms(elapsed)}", end="", flush=True)

                if line.startswith("progress=end"):
                    with print_lock:
                        ui.clear_line()
                    break

            process.wait()
            stderr_thread.join(timeout=5)
            render_time = time.time() - start_time

            if process.returncode != 0:
                detail = "\n     ".join(stderr_tail[-8:]) if stderr_tail else "keine Details"
                self.logger.error_and_exit(
                    f"FFmpeg-Render fehlgeschlagen (Code {process.returncode})\n"
                    f"     Letzte FFmpeg-Ausgaben:\n     {detail}"
                )

            ui.ok(f"Render abgeschlossen in {format_hms(render_time)}")
            self.logger.log(f"Render abgeschlossen: {output} "
                            f"(Renderzeit: {format_hms(render_time)})")
            return render_time

        except FileNotFoundError:
            self.logger.error_and_exit("FFmpeg wurde nicht gefunden (PATH pruefen).")
        except Exception as exc:
            self.logger.error_and_exit(f"FFmpeg-Render fehlgeschlagen: {exc}")
        return 0.0

    # -- ffprobe -----------------------------------------------------------

    def get_duration(self, input_file: str, use_cache: bool = False) -> float:
        """Gesamtdauer einer Videodatei in Sekunden."""
        if use_cache and input_file in self._duration_cache:
            return self._duration_cache[input_file]

        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", input_file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            duration = float(result.stdout.strip())
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else str(exc)
            self.logger.log(f"ffprobe fehlgeschlagen fuer {input_file}: {stderr}", "WARNING")
            duration = 0.0
        except (ValueError, FileNotFoundError) as exc:
            self.logger.log(f"Dauer nicht ermittelbar fuer {input_file}: {exc}", "WARNING")
            duration = 0.0

        if use_cache:
            self._duration_cache[input_file] = duration
        return duration

    def get_video_size(self, input_file: str) -> Optional[Tuple[int, int]]:
        """Liefert (Breite, Hoehe) des Videostreams.

        NEU in v2.4.0: Der concat-Filter braucht eine feste Zielaufloesung,
        auf die alle Eingaenge skaliert werden.
        """
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height",
               "-of", "csv=p=0:s=x", input_file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            parts = result.stdout.strip().split("x")
            return int(parts[0]), int(parts[1])
        except Exception as exc:
            self.logger.log(f"Aufloesung nicht ermittelbar fuer {input_file}: {exc}",
                            "WARNING")
            return None

    def get_creation_time(self, input_file: str) -> Optional[str]:
        """Liest das eingebettete Aufnahmedatum (creation_time)."""
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
               "-of", "default=noprint_wrappers=1:nokey=1", input_file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            raw = result.stdout.strip()
            if raw and re.match(r"^\d{4}-\d{2}-\d{2}$", raw[:10]):
                return raw[:10]
            return None
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return None

    def get_stream_summary(self, input_file: str) -> str:
        """Kurzuebersicht der Streams einer Datei (Diagnose)."""
        cmd = ["ffprobe", "-v", "error",
               "-show_entries", "stream=codec_type,codec_name,width,height",
               "-of", "csv=p=0", input_file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            return "; ".join(lines) if lines else "keine Stream-Info"
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return "keine Stream-Info"


# ============================================================================
# VLC-Player
# ============================================================================

class VLCPlayer:
    """Spielt Vorschauen ab. Fehler beenden nie das Programm."""

    VLC_PATHS = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        os.path.expandvars(r"%PROGRAMFILES%\VideoLAN\VLC\vlc.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\VideoLAN\VLC\vlc.exe"),
    ]

    def __init__(self, logger: Logger):
        self.logger = logger
        self.vlc_path = self._find_vlc()
        if not self.vlc_path:
            ui.warn("VLC nicht gefunden - Vorschauen werden uebersprungen.")
            ui.detail("Rendern und Hochladen funktionieren trotzdem.")
            self.logger.log("VLC nicht gefunden", "WARNING")

    def _find_vlc(self) -> Optional[str]:
        if shutil.which("vlc"):
            self.logger.log("VLC im PATH gefunden")
            return "vlc"
        for path in self.VLC_PATHS:
            if Path(path).exists():
                self.logger.log(f"VLC gefunden: {path}")
                return path
        return None

    def play(self, file: str, duration: Optional[int] = None,
             force_foreground: bool = True) -> bool:
        """Spielt eine Datei ab. Ein Fehler wird nur protokolliert.

        Vorschau ist Komfort und darf den Ablauf nie abbrechen - bis v2.1.0
        beendete ein per Klick geschlossenes VLC-Fenster das gesamte
        Programm inklusive aller bereits getroffenen Einstellungen.
        """
        if not self.vlc_path:
            return False
        if not Path(file).exists():
            self.logger.log(f"Vorschaudatei fehlt: {file}", "WARNING")
            return False

        cmd = [self.vlc_path, "--play-and-exit", "--video-on-top", "--no-video-title-show"]
        kwargs: Dict[str, Any] = {}

        if sys.platform == "win32" and force_foreground:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = SW_SHOWNORMAL
            kwargs["startupinfo"] = startupinfo

        if duration:
            cmd.extend(["--stop-time", str(duration)])
        cmd.append(file)

        self.logger.log(f"VLC startet: {file}")
        try:
            subprocess.run(cmd, **kwargs)
            self.logger.log("VLC Wiedergabe beendet")
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            self.logger.log(f"VLC nicht startbar: {exc}", "WARNING")
            ui.warn(f"Vorschau nicht moeglich: {exc}")
            return False


# ============================================================================
# Upload-Marker
# ============================================================================

class UploadMarker:
    """Verwaltet die .uploaded.json-Marker fuer wiederaufnehmbare Uploads.

    Der Marker fuehrt eine HISTORIE aller Uploads einer Datei statt nur des
    letzten. Beim Re-Upload aus dem Archiv (Uploadmodus) waere sonst die
    urspruengliche YouTube-ID verloren - und damit die Information, welches
    Video wann wohin gegangen ist.

    Aufbau:
        youtube_video_id  = ID des JUENGSTEN Uploads (Abwaertskompatibilitaet,
                            alle bestehenden Pruefungen lesen dieses Feld)
        uploads           = Liste aller Uploads, aeltester zuerst

    Marker aus frueheren Versionen kennen 'uploads' nicht. Sie werden beim
    naechsten Schreiben automatisch uebernommen, indem der vorhandene
    Einzelupload als erster Listeneintrag rekonstruiert wird.
    """

    def __init__(self, logger: Logger, playlist_id: str):
        self.logger = logger
        self.playlist_id = playlist_id

    def marker_path(self, video_path: Path) -> Path:
        return video_path.with_name(video_path.name + ".uploaded.json")

    def _read_raw(self, path: Path) -> Optional[Dict[str, Any]]:
        """Liest den Marker ohne Gueltigkeitspruefung."""
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            return None

    def write_marker(self, video_path: Path, youtube_video_id: str, title: str,
                     privacy: str = "", playlist_id: Optional[str] = None) -> Dict[str, Any]:
        """Schreibt bzw. ergaenzt den Uploadmarker."""
        path = self.marker_path(video_path)
        effective_playlist = playlist_id if playlist_id is not None else self.playlist_id

        # Bestehende Historie uebernehmen, damit frueherer Upload nicht verloren geht.
        history: List[Dict[str, Any]] = []
        existing = self._read_raw(path)
        if existing:
            if isinstance(existing.get("uploads"), list):
                history = [e for e in existing["uploads"] if isinstance(e, dict)]
            elif existing.get("youtube_video_id"):
                # Marker aus v2.2.0 oder aelter -> in das neue Format ueberfuehren.
                history = [{
                    "youtube_video_id": existing.get("youtube_video_id"),
                    "title": existing.get("title", ""),
                    "privacy_status": existing.get("privacy_status", ""),
                    "playlist_id": existing.get("playlist_id", ""),
                    "uploaded_at_utc": existing.get("uploaded_at_utc", ""),
                }]
                self.logger.log(f"Alten Uploadmarker in Historienformat ueberfuehrt: {path}")

        history.append({
            "youtube_video_id": youtube_video_id,
            "title": title,
            "privacy_status": privacy,
            "playlist_id": effective_playlist,
            "uploaded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

        payload = {
            "youtube_video_id": youtube_video_id,   # juengster Upload
            "source": "youtube_upload",
            "video_filename": video_path.name,
            "title": title,
            "privacy_status": privacy,
            "playlist_id": effective_playlist,
            "uploaded_at_utc": history[-1]["uploaded_at_utc"],
            "upload_count": len(history),
            "uploads": history,
        }

        temporary = path.with_name(path.name + ".part")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding='utf-8')
        os.replace(temporary, path)

        if len(history) > 1:
            self.logger.log(f"Uploadmarker ergaenzt (Upload Nr. {len(history)}): {path}")
        else:
            self.logger.log(f"Uploadmarker geschrieben: {path}")
        return payload

    def read_marker(self, video_path: Path) -> Optional[Dict[str, Any]]:
        """Liest den Marker und prueft ihn auf Gueltigkeit."""
        path = self.marker_path(video_path)
        payload = self._read_raw(path)
        if payload is None:
            if path.is_file():
                self.logger.log(f"Ungueltiger Uploadmarker: {path}", "WARNING")
            return None
        if not payload.get("youtube_video_id"):
            self.logger.log(f"Uploadmarker ohne Video-ID: {path}", "WARNING")
            return None
        return payload

    @staticmethod
    def upload_count(payload: Optional[Dict[str, Any]]) -> int:
        """Anzahl der bisherigen Uploads laut Marker."""
        if not payload:
            return 0
        uploads = payload.get("uploads")
        if isinstance(uploads, list) and uploads:
            return len(uploads)
        return 1 if payload.get("youtube_video_id") else 0


# ============================================================================
# Archiv-Manager
# ============================================================================

class ArchiveManager:
    """Verschiebt fertige Videos nach erfolgreichem Upload ins Archiv."""

    def __init__(self, logger: Logger, config: Config, marker: UploadMarker):
        self.logger = logger
        self.cfg = config
        self.marker = marker
        self.archive_dir = config.archiv_dir
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def archive_with_retry(self, video_path: Path) -> Tuple[bool, Optional[Path]]:
        """Verschiebt die Datei ins Archiv. Rueckgabe: (Erfolg, Zielpfad).

        Bei einem Namenskonflikt mit abweichender Groesse wird nicht fatal
        abgebrochen, sondern ein eindeutiger Alternativname verwendet - sonst
        bliebe ein bereits hochgeladenes Video unauffindbar im Ausgabeordner
        liegen. Der tatsaechliche Zielpfad wird zurueckgegeben, damit die
        Abschlussmeldung keinen Pfad nennt, unter dem nichts liegt.
        """
        max_attempts = self.cfg.archiv_versuche
        delay = self.cfg.archiv_wartezeit

        target = self.archive_dir / video_path.name
        marker = self.marker.marker_path(video_path)

        for attempt in range(1, max_attempts + 1):
            try:
                if target.exists() and video_path.stat().st_size != target.stat().st_size:
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    target = self.archive_dir / (
                        f"{video_path.stem}_conflict_{stamp}{video_path.suffix}")
                    self.logger.log(f"Namenskonflikt im Archiv - weiche aus auf: {target}",
                                    "WARNING")

                if target.exists():
                    # Nur erreichbar bei identischer Groesse (echtes Duplikat).
                    try:
                        video_path.unlink()
                        self.logger.log(f"Duplikat entfernt: {video_path}")
                    except PermissionError:
                        self.logger.log(f"Quelldatei gesperrt: {video_path}", "WARNING")
                    return True, target

                os.replace(video_path, target)
                if marker.exists():
                    os.replace(marker, target.with_name(target.name + ".uploaded.json"))
                self.logger.log(f"Archivierung erfolgreich: {target}")
                return True, target

            except PermissionError:
                if attempt == max_attempts:
                    self.logger.log(f"Archivierung nach {max_attempts} Versuchen "
                                    f"weiterhin gesperrt: {video_path}", "ERROR")
                    return False, None
                ui.detail(f"Datei noch gesperrt - Versuch {attempt}/{max_attempts}, "
                          f"erneut in {delay}s")
                self.logger.log(f"Archivierung gesperrt, Versuch {attempt}/{max_attempts}",
                                "WARNING")
                time.sleep(delay)
            except OSError as exc:
                self.logger.log(f"Archivierung fehlgeschlagen: {exc}", "ERROR")
                return False, None

        return False, None


# ============================================================================
# Beschreibungs-Vorlagen
# ============================================================================

class BeschreibungTemplateManager:
    """Sucht und parst Beschreibungs-Vorlagen aus dem Zentralordner."""

    HEADER_MAP = {
        "titel": "title", "title": "title",
        "beschreibung": "description", "description": "description",
        "tags": "tags",
        "aufnahmedatum": "recording_date",
        "sichtbarkeit": "privacy_status",
    }
    FILENAME_PATTERNS = ["*-beschreibung.md", "*_beschreibung.md"]

    def __init__(self, logger: Logger, templates_dir: Path):
        self.logger = logger
        self.templates_dir = templates_dir

    def find_templates(self) -> List[Path]:
        if not self.templates_dir.exists():
            self.logger.log(f"Vorlagenordner fehlt: {self.templates_dir}", "WARNING")
            return []

        seen = set()
        files: List[Path] = []
        for pattern in self.FILENAME_PATTERNS:
            for f in self.templates_dir.rglob(pattern):
                if f not in seen:
                    seen.add(f)
                    files.append(f)

        files.sort(key=lambda f: f.name.lower())
        self.logger.log(f"{len(files)} Beschreibungs-Vorlage(n) gefunden")
        return files

    def parse(self, path: Path) -> Dict[str, str]:
        """Parst eine Vorlage anhand von '# Ueberschrift'-Abschnitten."""
        try:
            raw = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:
            self.logger.log(f"Vorlage nicht lesbar: {path} ({exc})", "WARNING")
            return {}

        raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)

        sections: Dict[str, str] = {}
        current_key: Optional[str] = None
        current_lines: List[str] = []

        for line in raw.splitlines():
            heading = re.match(r"^#\s+(.+?)\s*$", line)
            if heading:
                if current_key:
                    sections[current_key] = "\n".join(current_lines).strip()
                current_key = self.HEADER_MAP.get(heading.group(1).strip().lower())
                current_lines = []
            elif current_key:
                current_lines.append(line)

        if current_key:
            sections[current_key] = "\n".join(current_lines).strip()

        result: Dict[str, str] = {}

        if sections.get("title"):
            result["title"] = sections["title"].splitlines()[0].strip()
        if sections.get("description"):
            result["description"] = sections["description"].strip()

        if sections.get("tags"):
            # Tags duerfen als Markdown-Liste ("- tag") oder kommagetrennt stehen.
            tags: List[str] = []
            for line in sections["tags"].splitlines():
                line = re.sub(r"^\s*[-*+]\s+", "", line).strip()
                for part in line.split(","):
                    part = part.strip()
                    if part and part not in tags:
                        tags.append(part)
            if tags:
                result["tags"] = ", ".join(tags)

        if sections.get("recording_date"):
            candidate = sections["recording_date"].strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", candidate):
                result["recording_date"] = candidate
            elif candidate:
                self.logger.log(f"Ungueltiges Aufnahmedatum in Vorlage: '{candidate}'",
                                "WARNING")

        if sections.get("privacy_status"):
            candidate = sections["privacy_status"].strip().lower()
            if candidate in VALID_PRIVACY:
                result["privacy_status"] = candidate
            elif candidate:
                self.logger.log(f"Ungueltige Sichtbarkeit in Vorlage: '{candidate}'",
                                "WARNING")

        return result


# ============================================================================
# YouTube-Uploader
# ============================================================================

class YouTubeUploader:
    """Upload mit OAuth, Chunk-Fortschritt und Playlist-Zuordnung."""

    def __init__(self, logger: Logger, config: Config):
        self.logger = logger
        self.cfg = config
        self.youtube = None
        self._ensure_dependencies()

    def _ensure_dependencies(self) -> None:
        try:
            from google.auth.transport.requests import Request  # noqa: F401
            from google.oauth2.credentials import Credentials  # noqa: F401
            from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
            from googleapiclient.discovery import build  # noqa: F401
            from googleapiclient.http import MediaFileUpload  # noqa: F401
            self.logger.log("YouTube-API-Pakete verfuegbar")
        except ImportError as exc:
            self.logger.error_and_exit(
                f"YouTube-API-Pakete fehlen: {exc}\n"
                "     Bitte installieren:\n"
                "     pip install google-api-python-client google-auth-oauthlib "
                "google-auth-httplib2"
            )

    def _get_credentials(self) -> Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        token_path = Path(self.cfg.yt_token_file)
        client_path = Path(self.cfg.yt_client_secrets)
        scopes = ["https://www.googleapis.com/auth/youtube"]
        credentials = None

        if token_path.exists():
            try:
                credentials = Credentials.from_authorized_user_file(str(token_path), scopes)
                self.logger.log(f"Token-Datei geladen: {token_path}")
            except Exception as exc:
                self.logger.log(f"Token ungueltig: {exc}", "WARNING")
                credentials = None

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                self.logger.log("Token wird erneuert...")
                credentials.refresh(Request())
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(credentials.to_json(), encoding='utf-8')
                self.logger.log("Erneuertes Token gespeichert")
            else:
                if not client_path.exists():
                    self.logger.error_and_exit(f"YouTube Client-Datei fehlt: {client_path}")
                ui.info("Anmeldung im Browser erforderlich...")
                flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes)
                credentials = flow.run_local_server(port=0)
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(credentials.to_json(), encoding='utf-8')
                self.logger.log("Token gespeichert")

        return credentials

    def get_service(self) -> Any:
        from googleapiclient.discovery import build
        if self.youtube is None:
            self.youtube = build("youtube", "v3", credentials=self._get_credentials())
            self.logger.log("YouTube-Service initialisiert")
        return self.youtube

    def build_tag_list(self, custom_tags: str = "") -> List[str]:
        """Standard-Tags plus individuelle Tags, ohne Dubletten."""
        tags = list(self.cfg.yt_tags)
        if custom_tags:
            for tag in (t.strip() for t in custom_tags.split(",")):
                if tag and tag not in tags:
                    tags.append(tag)
        return tags

    def upload_video(self, video_path: Path, title: str, description: str,
                     recording_date: str, custom_tags: str = "",
                     privacy_override: Optional[str] = None) -> Tuple[str, float]:
        """Laedt das Video hoch. Rueckgabe: (Video-ID, Dauer in Sekunden).

        Der Upload nutzt die Chunk-Schleife von next_chunk() statt eines
        einzigen execute()-Aufrufs - sonst laeuft ein mehrere GB grosser
        Upload minutenlang ohne Ausgabe, und ein Netzabbruch bedeutet den
        vollstaendigen Neustart der Uebertragung.
        """
        from googleapiclient.http import MediaFileUpload

        youtube = self.get_service()
        tags = self.build_tag_list(custom_tags)
        effective_privacy = privacy_override or self.cfg.yt_privacy

        ui.detail(f"Tags: {', '.join(tags)}")
        self.logger.log(f"Finale Tags: {tags}")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": self.cfg.yt_category_id,
            },
            "status": {
                "privacyStatus": effective_privacy,
                "publicStatsViewable": self.cfg.yt_public_stats,
                "embeddable": self.cfg.yt_embeddable,
                "license": self.cfg.yt_license,
                "selfDeclaredMadeForKids": self.cfg.yt_made_for_kids,
                "containsSyntheticMedia": self.cfg.yt_synthetic,
            },
            "recordingDetails": {"recordingDate": f"{recording_date}T00:00:00.000Z"},
        }

        size_mb = video_path.stat().st_size / (1024 * 1024)
        ui.plain(f"   {video_path.name}  ({size_mb:.0f} MB, Sichtbarkeit: "
                 f"{effective_privacy})")
        self.logger.log(f"Upload startet: {video_path.name} ({size_mb:.0f} MB)")
        self.logger.log(f"Titel: {title}")

        media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                                resumable=True, chunksize=8 * 1024 * 1024)
        request = youtube.videos().insert(
            part="snippet,status,recordingDetails", body=body, media_body=media)

        response = None
        start_time = time.time()
        retries = 0
        max_retries = 5

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    percent = int(status.progress() * 100)
                    elapsed = time.time() - start_time
                    eta = ""
                    if percent > 0:
                        remaining = max(0.0, elapsed / (percent / 100) - elapsed)
                        eta = f" | noch ca. {format_hms(remaining)}"
                    bar = ui.progress_bar(percent)
                    print(f"\r   [{bar}] {percent:3}%  "
                          f"{format_hms(elapsed)}{eta}   ", end="", flush=True)
                retries = 0
            except Exception as exc:
                retries += 1
                if retries > max_retries:
                    print()
                    raise
                wait = 2 ** retries
                ui.clear_line()
                ui.warn(f"Upload unterbrochen ({exc})")
                ui.detail(f"Wiederholung {retries}/{max_retries} in {wait}s...")
                self.logger.log(f"Upload-Chunk fehlgeschlagen ({exc}), "
                                f"Wiederholung {retries}/{max_retries}", "WARNING")
                time.sleep(wait)

        upload_time = time.time() - start_time
        ui.clear_line()

        video_id = response.get("id")
        if not video_id:
            raise RuntimeError("YouTube lieferte keine Video-ID")

        ui.ok(f"Upload abgeschlossen in {format_hms(upload_time)}")
        self.logger.log(f"Upload erfolgreich | YouTube-ID: {video_id}")
        return video_id, upload_time

    def add_to_playlist(self, video_id: str) -> bool:
        """Fuegt das Video der konfigurierten Playlist hinzu."""
        if not self.cfg.yt_playlist_id:
            self.logger.log("Keine Playlist-ID konfiguriert", "WARNING")
            return False

        try:
            self.get_service().playlistItems().insert(
                part="snippet",
                body={"snippet": {
                    "playlistId": self.cfg.yt_playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }},
            ).execute()
            self.logger.log(f"Playlist-Zuordnung erfolgreich: {self.cfg.yt_playlist_id}")
            return True
        except Exception as exc:
            self.logger.log(f"Playlist-Zuordnung fehlgeschlagen: {exc}", "WARNING")
            ui.warn(f"Playlist-Zuordnung fehlgeschlagen: {exc}")
            return False


# ============================================================================
# Eingabehilfen
# ============================================================================

def ask(prompt: str) -> str:
    """input() mit sauberem Abbruch bei Strg+C / Strg+Z."""
    try:
        return input(prompt)
    except (KeyboardInterrupt, EOFError):
        ui.plain()
        ui.plain()
        ui.plain(f"{ui.sym('wave')} Abbruch durch Benutzer. Programm wird beendet.")
        sys.exit(0)


def ask_yes_no(prompt: str) -> bool:
    """Ja/Nein-Abfrage mit toleranter Auswertung."""
    while True:
        choice = ask(f"{prompt} (j/n): ").strip().lower()
        if choice in ('j', 'ja', 'y', 'yes'):
            return True
        if choice in ('n', 'nein', 'no'):
            return False
        ui.plain("   Bitte 'j' oder 'n' eingeben.")


# ============================================================================
# Menue-Dialog
# ============================================================================

class MenuDialog:
    """Alle interaktiven Abfragen."""

    def __init__(self, logger: Logger, config: Config,
                 template_manager: BeschreibungTemplateManager):
        self.logger = logger
        self.cfg = config
        self.template_manager = template_manager

    # -- Aufnahmeauswahl ---------------------------------------------------

    def show_recording_list(self, recordings: List[Dict[str, Any]]) -> str:
        """Zeigt die Aufnahmen und gibt die Auswahl zurueck.

        Die Spalte hiess bis v2.1.0 'Dauer', zeigte aber die Wanduhr-
        Zeitspanne. Bei einem Zeitraffer liegt die Videolaenge um ein
        Vielfaches darunter - das sah nach fehlendem Material aus. Beide
        Werte stehen deshalb getrennt da.

        Der Zeitraum kommt aus derselben Quelle wie in Schritt 2/8
        (estimate_span) und zeigt bei fehlender Datenbasis 'unbekannt'.
        """
        ui.header("Verfuegbare Aufnahmen", "folder")
        ui.plain("   Zeitraum  = Wanduhrzeit der Aufnahme (inkl. erstem Chapter)")
        ui.plain("   Material  = tatsaechliche Laenge des Videomaterials")
        ui.rule("-")

        for index, rec in enumerate(recordings, 1):
            line = (f" {index:2}.  {rec['name']:<20} "
                    f"{rec['start']:<17} "
                    f"Zeitraum {rec['span_str']:>9}")
            if rec.get("material_str"):
                line += f"   Material {rec['material_str']:>12}"
            line += f"   {rec['file_count']:>2} Dateien"
            ui.plain(line)

        ui.rule("=")

        while True:
            choice = ask("Aufnahme waehlen (Nummer): ").strip()
            try:
                index = int(choice) - 1
            except ValueError:
                ui.plain("   Bitte eine Nummer eingeben.")
                continue
            if 0 <= index < len(recordings):
                selected = recordings[index]["name"]
                self.logger.log(f"Aufnahme gewaehlt: {selected}")
                return selected
            ui.plain("   Ungueltige Nummer.")

    # -- Einstellungen -----------------------------------------------------

    def get_target_fps(self) -> int:
        """Ziel-FPS abfragen - mit Vorbelegung aus der INI.

        Wurde nach einem erfolgreichen Lauf ein Wert gespeichert, erscheint
        er als Vorbelegung. Enter uebernimmt ihn, die ausfuehrliche
        Werteliste wird dann uebersprungen. Mit '?' laesst sie sich trotzdem
        anzeigen.
        """
        saved = self.cfg.ziel_fps

        if saved > 0:
            ui.section("Ziel-Framerate", "gear")
            ui.plain(f"   Zuletzt verwendet: {saved} FPS "
                     f"(gespeichert in {self.cfg.path.name})")
            while True:
                raw = ask(f"   Enter = {saved} uebernehmen, andere Zahl eingeben "
                          f"oder '?' fuer Empfehlungen: ").strip()
                if not raw:
                    self.logger.log(f"Ziel-FPS aus Config uebernommen: {saved}")
                    return saved
                if raw == "?":
                    self._print_fps_help()
                    continue
                try:
                    fps = int(raw)
                except ValueError:
                    ui.plain("   Bitte eine Zahl eingeben (oder Enter).")
                    continue
                if 1 <= fps <= 240:
                    self.logger.log(f"Ziel-FPS eingegeben: {fps}")
                    return fps
                ui.plain("   FPS muss zwischen 1 und 240 liegen.")

        ui.section("Ziel-Framerate", "gear")
        self._print_fps_help()
        while True:
            raw = ask("   Ziel-FPS (Enter = 60): ").strip()
            try:
                fps = int(raw or "60")
            except ValueError:
                ui.plain("   Bitte eine Zahl eingeben.")
                continue
            if 1 <= fps <= 240:
                self.logger.log(f"Ziel-FPS eingegeben: {fps}")
                return fps
            ui.plain("   FPS muss zwischen 1 und 240 liegen.")

    @staticmethod
    def _print_fps_help() -> None:
        ui.plain("    24  Kino-Look          50  PAL High FPS")
        ui.plain("    25  PAL (Europa)       60  NTSC High FPS, sehr fluessig")
        ui.plain("    30  NTSC, fluessig    120  Ultra Smooth")

    def get_test_preview_duration(self) -> int:
        """Dauer des Testrenders abfragen."""
        default = self.cfg.testrender_dauer
        ui.section("Testrender-Dauer", "clock")
        ui.plain("   Laenge der Testvorschau. Empfehlung: 20-60s.")
        ui.detail("Reicht das Material nicht aus, wird automatisch verkuerzt.")

        while True:
            raw = ask(f"   Dauer in Sekunden (Enter = {default}): ").strip()
            try:
                duration = int(raw) if raw else default
            except ValueError:
                ui.plain("   Bitte eine Zahl eingeben.")
                continue
            if 1 <= duration <= 300:
                self.logger.log(f"Testrender-Dauer: {duration}s")
                return duration
            ui.plain("   Bitte einen Wert zwischen 1 und 300 eingeben.")

    def get_speed_factor(self, material_seconds: float = 0.0) -> float:
        """Geschwindigkeitsfaktor abfragen, mit Vorschau der Ergebnislaenge."""
        if material_seconds > 0:
            ui.plain(f"   Videomaterial: {format_material_len(material_seconds)}")
            parts = [f"Faktor {f:g} = {format_material_len(material_seconds / f)}"
                     for f in (2, 4, 6, 10)]
            ui.detail("   ".join(parts))

        while True:
            raw = ask("   Geschwindigkeitsfaktor (z.B. 6): ").strip()
            try:
                factor = float(raw.replace(",", "."))
            except ValueError:
                ui.plain("   Bitte eine Zahl eingeben (z.B. 6 oder 2.5).")
                continue
            if factor > 0:
                self.logger.log(f"Faktor eingegeben: {factor}")
                return factor
            ui.plain("   Der Faktor muss groesser als 0 sein.")

    def confirm_preview(self) -> bool:
        return ask_yes_no("   Zufrieden mit der Vorschau?")

    # -- Job-Details -------------------------------------------------------

    def prompt_title(self, recording_date: str) -> str:
        ui.plain(f"   Format: {recording_date} - [Titel]")
        title = ask("   Titel: ").strip()
        if not title.startswith(recording_date):
            title = f"{recording_date} - {title}"
        return title

    def prompt_description_body(self) -> str:
        """Fragt NUR den Textkoerper ab - der Kopfbereich entsteht zentral."""
        ui.plain("   Beschreibung (mehrzeilig, leere Zeile beendet die Eingabe):")
        ui.detail("Kopfzeilen (Datum, Kamera, Aufnahmezeitraum) werden automatisch "
                  "vorangestellt.")
        lines = []
        while True:
            line = ask("   > ")
            if line == "":
                break
            lines.append(line)
        return "\n".join(lines)

    def prompt_tags(self) -> str:
        ui.detail(f"Standard-Tags: {', '.join(self.cfg.yt_tags)}")
        return ask("   Zusaetzliche Tags (Komma-getrennt, Enter = keine): ").strip()

    def select_beschreibung_template(self, templates: List[Path],
                                     allow_manual: bool = True) -> Optional[Path]:
        """Laesst eine Beschreibungs-Vorlage auswaehlen."""
        ui.plain()
        ui.plain(f"   {ui.sym('note')} Beschreibungs-Vorlagen:")
        if allow_manual:
            ui.plain("     0.  (keine) - alles manuell eingeben")
        for index, template in enumerate(templates, 1):
            try:
                label = template.relative_to(self.cfg.beschreibung_dir)
            except ValueError:
                label = template.name
            ui.plain(f"    {index:2}.  {label}")

        prompt = ("   Vorlage waehlen (Nummer, 0 = manuell): " if allow_manual
                  else "   Vorlage waehlen (Nummer): ")

        while True:
            choice = ask(prompt).strip()
            try:
                index = int(choice)
            except ValueError:
                ui.plain("   Bitte eine Nummer eingeben.")
                continue
            if index == 0 and allow_manual:
                return None
            if 1 <= index <= len(templates):
                selected = templates[index - 1]
                self.logger.log(f"Vorlage gewaehlt: {selected}")
                return selected
            ui.plain("   Ungueltige Nummer.")

    def get_job_details(self, recording_date: str,
                        period_str: str = "") -> Tuple[str, str, str, str, Optional[str]]:
        """Ermittelt Titel, Beschreibung und Tags - optional aus einer Vorlage.

        period_str ist die WANDUHRZEIT der Aufnahme, nicht die Laenge des
        Videomaterials.
        """
        prefill: Dict[str, str] = {}
        templates = self.template_manager.find_templates()

        if templates:
            chosen = self.select_beschreibung_template(templates)
            if chosen:
                prefill = self.template_manager.parse(chosen)
                ui.ok(f"Vorlage geladen: {chosen.name}")
                if not prefill:
                    ui.detail("Keine erkennbaren Abschnitte - alles wird manuell abgefragt.")
                for key, value in prefill.items():
                    preview = value.replace("\n", " ")
                    if len(preview) > 70:
                        preview = preview[:67] + "..."
                    ui.detail(f"{key}: {preview}")

        effective_date = prefill.get("recording_date", recording_date)
        if "recording_date" in prefill:
            ui.info(f"Aufnahmedatum aus Vorlage: {effective_date}")
            self.logger.log(f"Aufnahmedatum durch Vorlage ueberschrieben: {effective_date}")

        # Titel
        if prefill.get("title"):
            title = prefill["title"]
            # Praefix nur ergaenzen, wenn noch kein Datum am Anfang steht -
            # sonst entstuende bei abweichendem Vorlagendatum ein doppeltes.
            if not re.match(r"^\d{4}-\d{2}-\d{2}", title):
                title = f"{effective_date} - {title}"
        else:
            title = self.prompt_title(effective_date)

        # Beschreibung - Kopfbereich kommt in BEIDEN Zweigen aus build_description()
        body = prefill.get("description") or self.prompt_description_body()
        description = build_description(effective_date, body, period_str)

        custom_tags = prefill.get("tags") or self.prompt_tags()
        privacy_override = prefill.get("privacy_status")

        if privacy_override:
            ui.info(f"Sichtbarkeit aus Vorlage: {privacy_override}")
            self.logger.log(f"Sichtbarkeit durch Vorlage: {privacy_override}")

        self.logger.log(f"Titel final: {title}")
        self.logger.log(f"Beschreibung: {len(description)} Zeichen")
        return title, description, custom_tags, effective_date, privacy_override

    # -- Bestaetigungen ----------------------------------------------------

    def confirm_job(self, groups: List[Tuple[str, List[Tuple[str, Any]]]]) -> bool:
        """Zeigt die Auftragszusammenfassung gruppiert an."""
        ui.header("Auftragszusammenfassung", "note")
        for group_name, entries in groups:
            if group_name:
                ui.plain(f"  {ui._c(group_name, ui._BOLD)}")
            for key, value in entries:
                ui.kv(key, value)
            ui.plain()
        ui.rule("=")
        ui.warn("Nach der Bestaetigung laufen Rendern und Upload ohne weitere Eingabe.")
        ui.rule("=")
        return ask_yes_no("Jetzt rendern und hochladen?")

    def confirm_overwrite(self, output_path: Path) -> bool:
        """Warnt vor dem Ueberschreiben eines noch nicht hochgeladenen Videos."""
        size_mb = output_path.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(output_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        ui.plain()
        ui.warn("Es existiert bereits ein gerendertes Video mit diesem Namen:")
        ui.plain(f"   {output_path.name}  ({size_mb:.0f} MB, erstellt {mtime})")
        ui.plain("   Ein Uploadmarker fehlt - es wurde also vermutlich noch nicht "
                 "hochgeladen.")
        return ask_yes_no("   Trotzdem ueberschreiben?")

    def show_pending_uploads(self, pending: List[Path]) -> List[Path]:
        """Zeigt gerenderte Videos ohne Uploadmarker zur Auswahl."""
        ui.header("Offene Uploads gefunden", "up")
        ui.plain("   Diese Videos wurden gerendert, aber noch nicht hochgeladen:")
        ui.plain()
        for index, video in enumerate(pending, 1):
            size_mb = video.stat().st_size / (1024 * 1024)
            mtime = datetime.fromtimestamp(video.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            ui.plain(f"   {index:2}.  {video.name:<34} {size_mb:>6.0f} MB   {mtime}")
        ui.plain()
        ui.plain("   a       = alle hochladen")
        ui.plain("   1,3     = einzelne Nummern")
        ui.plain("   2-5     = Bereich")
        ui.plain("   n       = ueberspringen")

        while True:
            choice = ask("   Auswahl: ").strip().lower()
            if choice in ('n', 'nein', 'no', ''):
                self.logger.log("Offene Uploads uebersprungen")
                return []
            if choice in ('a', 'alle', 'all'):
                self.logger.log(f"Alle {len(pending)} offenen Uploads gewaehlt")
                return list(pending)

            indices = parse_selection(choice, len(pending))
            if indices:
                return [pending[i] for i in indices]
            ui.plain("   Bitte 'a', 'n', Nummern (1,3) oder Bereiche (2-5) eingeben.")

    def confirm_continue_with_new_job(self) -> bool:
        return ask_yes_no("Moechtest du jetzt eine neue Aufnahme verarbeiten?")

    # -- Uploadmodus -------------------------------------------------------

    def select_upload_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Zeigt alle hochladbaren Videos und laesst eine Auswahl treffen.

        Anders als show_pending_uploads() listet diese Ansicht BEIDE Ordner
        (Archiv und Ausgabe) und zeigt je Datei den Uploadstatus. Da im
        Archiv per Definition bereits hochgeladene Dateien liegen, ist die
        Kennzeichnung entscheidend, damit nicht versehentlich Dubletten auf
        YouTube entstehen.
        """
        ui.header("Videos zum Hochladen", "up")
        ui.plain("   Quelle  A = Archiv (bereits verarbeitet)   "
                 "O = Ausgabeordner (frisch gerendert)")
        ui.rule("-")

        for index, entry in enumerate(candidates, 1):
            marker = entry["marker"]
            size_mb = entry["size_mb"]
            mtime = entry["mtime"]

            if marker:
                count = UploadMarker.upload_count(marker)
                suffix = f" x{count}" if count > 1 else ""
                status = ui._c(f"hochgeladen{suffix}: "
                               f"{marker.get('youtube_video_id', '?')}", ui._YELLOW)
            else:
                status = ui._c("noch nicht hochgeladen", ui._GREEN)

            ui.plain(f" {index:2}. [{entry['origin_short']}] {entry['path'].name:<30} "
                     f"{size_mb:>6.0f} MB  {mtime}  {status}")

        ui.rule("=")
        ui.plain("   a       = alle")
        ui.plain("   1,3     = einzelne Nummern")
        ui.plain("   2-5     = Bereich")
        ui.plain("   1,4-6   = Kombination")
        ui.plain("   n       = abbrechen")

        while True:
            choice = ask("   Auswahl: ").strip().lower()
            if choice in ('n', 'nein', 'no', ''):
                self.logger.log("Uploadmodus vom Benutzer abgebrochen")
                return []
            if choice in ('a', 'alle', 'all'):
                self.logger.log(f"Alle {len(candidates)} Videos gewaehlt")
                return list(candidates)

            indices = parse_selection(choice, len(candidates))
            if indices:
                selected = [candidates[i] for i in indices]
                self.logger.log(f"{len(selected)} Video(s) zum Upload gewaehlt")
                return selected
            ui.plain("   Bitte 'a', 'n', Nummern (1,3), Bereiche (2-5) "
                     "oder Kombinationen (1,4-6) eingeben.")

    def confirm_reupload(self, already_uploaded: List[Dict[str, Any]]) -> bool:
        """Einmalige Rueckfrage, bevor bereits hochgeladene Videos erneut gehen.

        Warnen statt blockieren: Ein Re-Upload kann gewollt sein (geloeschtes
        Video, anderer Kanal, andere Playlist), soll aber nie unbemerkt
        passieren.
        """
        ui.plain()
        ui.warn(f"{len(already_uploaded)} der ausgewaehlten Videos wurden bereits "
                "hochgeladen:")
        for entry in already_uploaded:
            marker = entry["marker"]
            video_id = marker.get("youtube_video_id", "?")
            when = (marker.get("uploaded_at_utc", "") or "")[:10]
            ui.plain(f"   - {entry['path'].name:<32} https://youtu.be/{video_id}"
                     f"{'   am ' + when if when else ''}")
        ui.plain()
        ui.plain("   Ein erneuter Upload erzeugt ein ZWEITES Video auf YouTube.")
        ui.detail("Die bisherigen IDs bleiben im Uploadmarker erhalten.")
        return ask_yes_no("   Trotzdem erneut hochladen?")

    def select_batch_privacy(self, default: str) -> str:
        """Fragt die Sichtbarkeit EINMAL fuer den gesamten Stapel ab."""
        ui.section("Sichtbarkeit fuer diesen Stapel", "gear")
        for index, value in enumerate(VALID_PRIVACY, 1):
            hint = "  (Standard aus Config)" if value == default else ""
            ui.plain(f"    {index}.  {value}{hint}")

        while True:
            raw = ask(f"   Auswahl (Enter = {default}): ").strip().lower()
            if not raw:
                return default
            if raw in VALID_PRIVACY:
                return raw
            if raw.isdigit() and 1 <= int(raw) <= len(VALID_PRIVACY):
                return VALID_PRIVACY[int(raw) - 1]
            ui.plain(f"   Bitte eine Nummer oder einen der Werte eingeben: "
                     f"{', '.join(VALID_PRIVACY)}")

    def confirm_batch(self, entries: List[Dict[str, Any]], template_name: str,
                      privacy: str, dry_run: bool) -> bool:
        """Zeigt die Stapeluebersicht und laesst sie bestaetigen."""
        ui.header("Stapel-Upload: Zusammenfassung", "note")

        total_mb = sum(e["size_mb"] for e in entries)
        reupload_count = sum(1 for e in entries if e["marker"])

        ui.kv("Videos", len(entries), 26)
        ui.kv("Gesamtgroesse", f"{total_mb / 1024:.1f} GB", 26)
        ui.kv("Beschreibungs-Vorlage", template_name, 26)
        ui.kv("Sichtbarkeit", privacy, 26)
        if reupload_count:
            ui.kv("davon erneute Uploads", reupload_count, 26)
        ui.plain()

        for entry in entries:
            flag = " (erneut)" if entry["marker"] else ""
            ui.plain(f"   {entry['title']}{flag}")
            ui.detail(f"{entry['path'].name}  |  {entry['size_mb']:.0f} MB"
                      f"{'  |  ' + entry['period_str'] if entry['period_str'] else ''}")

        ui.rule("=")
        if dry_run:
            ui.info("Trockenlauf - es wird nichts hochgeladen oder veraendert.")
            return True

        ui.warn("Nach der Bestaetigung laeuft der gesamte Stapel ohne weitere Eingabe.")
        ui.rule("=")
        return ask_yes_no("Stapel jetzt hochladen?")


# ============================================================================
# Hauptprozessor
# ============================================================================

class GoProTimeLapseProcessor:
    """Buendelt alle Arbeitsschritte."""

    def __init__(self, config: Config, upload_only: bool = False):
        """
        upload_only=True ueberspringt Encoder-Erkennung und VLC-Suche.

        Im Uploadmodus (-u) wird weder gerendert noch eine Vorschau
        abgespielt. Die Encoder-Testencodes kosten mehrere Sekunden und
        waeren dort verschwendet.
        """
        self.cfg = config
        self.upload_only = upload_only
        self.base_dir = config.aufnahmen_dir
        self.logger = Logger(config.log_dir)
        self.ffmpeg = FFmpegHandler(self.logger, config, detect_encoder=not upload_only)
        self.vlc = VLCPlayer(self.logger) if not upload_only else None
        self.template_manager = BeschreibungTemplateManager(self.logger,
                                                            config.beschreibung_dir)
        self.menu = MenuDialog(self.logger, config, self.template_manager)
        self.uploader = YouTubeUploader(self.logger, config)
        self.marker = UploadMarker(self.logger, config.yt_playlist_id)
        self.archiver = ArchiveManager(self.logger, config, self.marker)

        for directory in (config.output_dir, config.temp_dir, config.beschreibung_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self._preview_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._material_cache: Dict[str, float] = {}
        self._span_cache: Dict[str, Tuple[float, Optional[float]]] = {}
        self._media_data_cache: Dict[str, Dict[str, Any]] = {}
        self._media_index_stats = {"hits": 0, "probed": 0, "updated_folders": 0}

        self.logger.log(f"GoProTimeLapseProcessor v{__VERSION__} initialisiert"
                        f"{' (Uploadmodus)' if upload_only else ''}")
        self.logger.log(f"Aufnahmen: {self.base_dir}")
        self.logger.log(f"Output: {config.output_dir}")
        self.logger.log(f"Archiv: {config.archiv_dir}")
        self.logger.log(f"Temp: {config.temp_dir}")

    # -- Dateien -----------------------------------------------------------

    def _sorted_mp4(self, folder: Path) -> List[Path]:
        """Alle MP4-Dateien eines Ordners in korrekter Reihenfolge."""
        files = list(folder.glob("*.MP4")) + list(folder.glob("*.mp4"))
        unique = list({f.resolve(): f for f in files}.values())
        sorted_files, _ = sort_gopro_files(unique)
        return sorted_files

    # -- Persistenter Medienindex -------------------------------------------
    def _read_media_index(self, folder: Path) -> Dict[str, Any]:
        """Liest den lokalen Medienindex. Fehler fuehren sicher zu Neuermittlung."""
        path = folder / MEDIA_INDEX_FILENAME
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.logger.log(f"Medienindex ungueltig fuer {folder.name}: {exc}", "WARNING")
            return {}
        if payload.get("schema_version") != MEDIA_INDEX_SCHEMA_VERSION:
            self.logger.log(
                f"Medienindex-Version fuer {folder.name} unbekannt; Index wird neu aufgebaut",
                "WARNING",
            )
            return {}
        files = payload.get("files")
        return payload if isinstance(files, dict) else {}

    def _write_media_index(self, folder: Path, payload: Dict[str, Any]) -> bool:
        """Schreibt den Medienindex atomar; ein Fehler stoppt die Verarbeitung nicht."""
        path = folder / MEDIA_INDEX_FILENAME
        temporary = folder / (MEDIA_INDEX_FILENAME + ".part")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
            return True
        except OSError as exc:
            self.logger.log(f"Medienindex nicht schreibbar fuer {folder.name}: {exc}", "WARNING")
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _get_media_data(self, folder: Path) -> Dict[str, Any]:
        """Liefert Dateidauern aus persistentem Index und prueft nur Aenderungen neu."""
        key = str(folder.resolve())
        cached = self._media_data_cache.get(key)
        if cached is not None:
            return cached

        mp4_files = self._sorted_mp4(folder)
        old_payload = self._read_media_index(folder)
        old_files = old_payload.get("files", {}) if old_payload else {}
        current_names = {f.name for f in mp4_files}
        changed = set(old_files) != current_names
        entries: Dict[str, Dict[str, Any]] = {}
        durations: Dict[str, float] = {}
        hits = 0
        probed = 0
        failures = 0

        for media_file in mp4_files:
            try:
                stat = media_file.stat()
            except OSError as exc:
                failures += 1
                changed = True
                self.logger.log(f"Dateistatus nicht lesbar fuer {media_file}: {exc}", "WARNING")
                continue
            signature = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            previous = old_files.get(media_file.name)
            duration = 0.0
            if (
                isinstance(previous, dict)
                and previous.get("size") == signature["size"]
                and previous.get("mtime_ns") == signature["mtime_ns"]
                and isinstance(previous.get("duration_seconds"), (int, float))
                and previous["duration_seconds"] > 0
            ):
                duration = float(previous["duration_seconds"])
                hits += 1
            else:
                changed = True
                probed += 1
                duration = self.ffmpeg.get_duration(str(media_file), use_cache=True)

            if duration > 0:
                durations[media_file.name] = duration
                entries[media_file.name] = {
                    **signature,
                    "duration_seconds": round(duration, 6),
                }
            else:
                failures += 1
                # Fehlerhafte Nullwerte werden bewusst nicht persistent gespeichert.

        total = sum(durations.values())
        complete = failures == 0 and len(durations) == len(mp4_files)
        payload = {
            "schema_version": MEDIA_INDEX_SCHEMA_VERSION,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "files": entries,
            "summary": {
                "file_count": len(mp4_files),
                "material_seconds": round(total, 6),
                "probe_failures": failures,
                "complete": complete,
            },
        }
        if changed or not old_payload:
            self._write_media_index(folder, payload)

        result = {
            "files": mp4_files,
            "durations": durations,
            "total": total,
            "failures": failures,
            "complete": complete,
            "cache_hits": hits,
            "probed": probed,
        }
        self._media_data_cache[key] = result
        self._material_cache[str(folder)] = total
        self._media_index_stats["hits"] += hits
        self._media_index_stats["probed"] += probed
        self._media_index_stats["updated_folders"] += int(changed or not old_payload)
        return result


    # -- Wanduhrzeit -------------------------------------------------------


    def estimate_span(self, folder: Path) -> Tuple[float, Optional[float]]:
        """Ermittelt die Wanduhrzeit inkl. erstem Chapter aus dem Medienindex."""
        cache_key = str(folder)
        if cache_key in self._span_cache:
            return self._span_cache[cache_key]
        media = self._get_media_data(folder)
        mp4_files = media["files"]
        if len(mp4_files) < 2:
            result = (0.0, None)
            self._span_cache[cache_key] = result
            if mp4_files:
                self.logger.log(
                    f"Wanduhrzeit fuer {folder.name} nicht bestimmbar: nur eine Datei"
                )
            return result
        clips = []
        for media_file in mp4_files:
            duration = media["durations"].get(media_file.name, 0.0)
            try:
                mtime = media_file.stat().st_mtime
            except OSError:
                mtime = 0.0
            clips.append((mtime, duration))
        raw_span = clips[-1][0] - clips[0][0]
        duration_rest = sum(item[1] for item in clips[1:])
        if raw_span <= 0 or duration_rest <= 0:
            result = (raw_span if raw_span > 0 else 0.0, None)
            self._span_cache[cache_key] = result
            return result
        ratio = raw_span / duration_rest
        if not (SPAN_RATIO_MIN <= ratio <= SPAN_RATIO_MAX):
            self.logger.log(
                f"Unplausibles Zeitraffer-Verhaeltnis {ratio:.1f} fuer {folder.name}; "
                "verwende die ungekorrigierte Zeitspanne.",
                "WARNING",
            )
            result = (raw_span, None)
            self._span_cache[cache_key] = result
            return result
        first_chapter_wall = ratio * clips[0][1]
        total_span = raw_span + first_chapter_wall
        self.logger.log(
            f"Wanduhrzeit {folder.name}: {format_h_min(raw_span)} gemessen + "
            f"{format_h_min(first_chapter_wall)} fuer das erste Chapter "
            f"(Verhaeltnis {ratio:.1f}x) = {format_h_min(total_span)}"
        )
        result = (total_span, ratio)
        self._span_cache[cache_key] = result
        return result
    def get_source_span(self, folder: Path) -> float:
        """Wanduhrzeit einer Aufnahme in Sekunden (0 = nicht bestimmbar).

        Nutzt dieselbe Logik wie die Aufnahmeliste, damit beide Stellen nie
        verschiedene Werte zeigen.
        """
        span, _ = self.estimate_span(folder)
        return span

    # -- Aufnahmen ---------------------------------------------------------


    def list_recordings(self) -> List[Dict[str, Any]]:
        """Alle Aufnahmeordner mit Zeitraum und persistenter Materiallaenge."""
        if not self.base_dir.exists():
            self.logger.error_and_exit(
                f"Aufnahmeverzeichnis existiert nicht: {self.base_dir}\n"
                f"     Pruefe [Verzeichnisse] in {self.cfg.path.name}."
            )
        folders = [f for f in self.base_dir.iterdir() if f.is_dir()]
        if self.cfg.materiallaenge_in_liste and folders:
            ui.plain(f"   Ermittle Aufnahmedaten in {len(folders)} Ordner(n)...")
        recordings: List[Dict[str, Any]] = []
        for folder in folders:
            media = self._get_media_data(folder)
            mp4_files = media["files"]
            if not mp4_files:
                continue
            times = [f.stat().st_mtime for f in mp4_files]
            material_seconds = media["total"] if self.cfg.materiallaenge_in_liste else 0.0
            material_str = (
                format_material_len(material_seconds)
                if self.cfg.materiallaenge_in_liste and material_seconds > 0
                else ""
            )
            span_seconds, span_ratio = self.estimate_span(folder)
            recordings.append({
                "name": folder.name,
                "start": datetime.fromtimestamp(min(times)).strftime("%Y-%m-%d %H:%M"),
                "span_seconds": span_seconds,
                "span_str": format_span(span_seconds),
                "span_ratio": span_ratio,
                "material_seconds": material_seconds,
                "material_str": material_str,
                "file_count": len(mp4_files),
            })
        recordings.sort(key=lambda r: r["start"], reverse=True)
        stats = self._media_index_stats
        if self.cfg.materiallaenge_in_liste and folders:
            ui.detail(
                f"Medienindex: {stats['hits']} Cachetreffer, "
                f"{stats['probed']} Datei(en) geprueft, "
                f"{stats['updated_folders']} Ordner aktualisiert"
            )
        self.logger.log(
            f"{len(recordings)} Aufnahmen gefunden; Medienindex: "
            f"{stats['hits']} Treffer, {stats['probed']} geprueft, "
            f"{stats['updated_folders']} Ordner aktualisiert"
        )
        return recordings
    def select_recording(self, folder_name: str) -> Path:
        selected = self.base_dir / folder_name
        if not selected.exists():
            self.logger.error_and_exit(f"Ordner existiert nicht: {selected}")
        self.logger.log(f"Ausgewaehlter Ordner: {selected}")
        return selected


    def get_total_source_duration(self, folder: Path) -> float:
        """Exakte Gesamtlaenge; nutzt den validierten persistenten Medienindex."""
        media = self._get_media_data(folder)
        total = media["total"]
        failures = media["failures"]
        if failures:
            ui.warn(
                f"Bei {failures} von {len(media['files'])} Dateien konnte die Dauer "
                "nicht ermittelt werden (beschaedigt oder noch nicht fertig kopiert?)."
            )
            self.logger.log(f"Dauer von {failures} Datei(en) nicht ermittelbar", "WARNING")
        self.logger.log(
            f"Materiallaenge ({len(media['files'])} Dateien): "
            f"{format_material_len(total)} ({total:.1f}s)"
        )
        return total
    def _source_folder_for_video(self, video_path: Path) -> Optional[Path]:
        """Leitet den Quellordner aus dem Namen eines gerenderten Videos ab."""
        name = video_path.stem
        if name.endswith("_final"):
            name = name[: -len("_final")]
        folder = self.base_dir / name
        return folder if folder.exists() and self._sorted_mp4(folder) else None

    def get_source_span_for_video(self, video_path: Path) -> Optional[float]:
        """Wanduhrzeit fuer ein fertiges Video, sofern der Quellordner noch da ist.

        Beim Upload aus dem Archiv ist der Quellordner oft laengst geloescht.
        Dann gibt es keine Wanduhrzeit - die Zeile entfaellt in der
        Beschreibung ersatzlos. Eine Rueckrechnung aus Videolaenge mal Faktor
        waere nicht moeglich, da der Faktor nirgends gespeichert wird.
        """
        folder = self._source_folder_for_video(video_path)
        if folder is None:
            return None
        span = self.get_source_span(folder)
        return span if span > 0 else None

    def get_total_source_duration_for_video(self, video_path: Path) -> Optional[float]:
        folder = self._source_folder_for_video(video_path)
        return self.get_total_source_duration(folder) if folder else None

    # -- Vorschau ----------------------------------------------------------

    def preview_first_clip(self, folder: Path) -> None:
        mp4_files = self._sorted_mp4(folder)
        if not mp4_files:
            self.logger.error_and_exit(f"Keine MP4-Dateien in {folder}")

        first = mp4_files[0]
        ui.plain(f"   {ui.sym('play')} {first.name} "
                 f"({self.cfg.erste_vorschau_dauer}s)")
        self.logger.log(f"Erste Vorschau: {first.name}")
        self.vlc.play(str(first), duration=self.cfg.erste_vorschau_dauer)

    def render_preview(self, folder: Path, factor: float, fps: int,
                       preview_duration: int) -> None:
        """Testrender aus der groessten LRV- bzw. MP4-Datei."""
        lrv_files = list(folder.glob("*.LRV")) + list(folder.glob("*.lrv"))
        if lrv_files:
            candidates = list({f.resolve(): f for f in lrv_files}.values())
            pattern, label = "*.LRV", "LRV"
        else:
            candidates = self._sorted_mp4(folder)
            pattern, label = "*.MP4", "MP4"

        if not candidates:
            self.logger.error_and_exit(f"Keine Dateien ({pattern}) in: {folder}")

        cache_key = (str(folder), pattern)
        cached = self._preview_cache.get(cache_key)

        if cached and Path(cached["path"]).exists():
            largest = Path(cached["path"])
            file_duration = cached["duration"]
        else:
            largest = max(candidates, key=lambda f: f.stat().st_size)
            size_mb = largest.stat().st_size / (1024 * 1024)
            file_duration = self.ffmpeg.get_duration(str(largest), use_cache=True)
            ui.detail(f"Quelle: groesste {label}-Datei {largest.name} "
                      f"({size_mb:.0f} MB, {file_duration:.0f}s)")
            self.logger.log(f"Testrender-Quelle: {largest.name} "
                            f"({size_mb:.1f} MB, {file_duration:.1f}s)")
            self._preview_cache[cache_key] = {"path": str(largest),
                                              "duration": file_duration}

        if file_duration <= 0:
            self.logger.error_and_exit(
                f"Dauer von {largest.name} nicht ermittelbar "
                "(ffprobe-Fehler oder beschaedigte Datei)."
            )

        required = preview_duration * factor
        actual = float(preview_duration)

        if file_duration < required - 0.5:
            actual = max(1.0, file_duration / factor)
            ui.warn(f"Material reicht nur fuer {actual:.0f}s statt {preview_duration}s "
                    f"(Faktor {factor} braucht {required:.0f}s Quelle).")
            self.logger.log(f"Testrender verkuerzt auf {actual:.1f}s", "WARNING")

        preview = str(self.cfg.temp_dir / f"preview_{preview_duration}s.mp4")
        self.ffmpeg.adjust_speed_with_progress(str(largest), preview, factor,
                                               fps=fps, duration=actual, is_test=True)
        ui.plain(f"   {ui.sym('play')} Vorschau wird abgespielt...")
        self.vlc.play(preview)
        self._safe_unlink(Path(preview))

    def _safe_unlink(self, path: Path) -> None:
        """Loescht eine Datei, ohne bei Sperren das Programm zu beenden."""
        if not path.exists():
            return
        for _ in range(3):
            try:
                path.unlink()
                self.logger.log(f"Temp-Datei geloescht: {path}")
                return
            except PermissionError:
                time.sleep(1)
            except OSError as exc:
                self.logger.log(f"Temp-Datei nicht loeschbar: {path} ({exc})", "WARNING")
                return
        self.logger.log(f"Temp-Datei blieb gesperrt: {path}", "WARNING")

    def cleanup_preview_temp_files(self) -> None:
        """Raeumt Reste der Vorschauphase weg.

        'combined.mp4' entsteht seit v2.4.0 nicht mehr; der Eintrag bleibt,
        um Altbestaende aus frueheren Versionen aufzuraeumen.
        """
        for name in ("combined_lrv.mp4", "combined.mp4", "filelist.txt"):
            self._safe_unlink(self.cfg.temp_dir / name)
        self._preview_cache.clear()

    # -- Finalrender -------------------------------------------------------

    def render_final(self, folder: Path, factor: float, fps: int, output_path: Path,
                     expected_source_duration: float) -> Tuple[bool, float]:
        """Finalrender in EINEM Durchgang. Rueckgabe: (vollstaendig, Renderzeit).

        Seit v2.4.0 ohne Zwischendatei - alle Chapter gehen direkt als
        Eingaenge in den concat-Filter. Geprueft wird deshalb die AUSGABE
        gegen 'Summe Quelldauern / Faktor'; vorher wurde die Zwischendatei
        gegen die Summe der Quelldauern geprueft.

        Eine erkannte Abweichung fuehrt bewusst NICHT zum Abbruch, wird aber
        am Ende noch einmal wiederholt - nach Stunden Render- und Uploadzeit
        ist die urspruengliche Warnung sonst aus dem Sichtbereich gescrollt.
        """
        files = self.ffmpeg.get_file_list(str(folder), file_pattern="*.MP4")
        expected_output = (expected_source_duration / factor
                           if expected_source_duration > 0 else 0.0)

        render_time = self.ffmpeg.render_from_files(
            files, str(output_path), factor, fps, expected_output)

        is_complete = True

        if expected_output > 0:
            actual = self.ffmpeg.get_duration(str(output_path))
            diff = expected_output - actual
            tolerance = max(1.0, expected_output * 0.02)

            if diff > tolerance:
                is_complete = False
                ui.plain()
                ui.warn("Das Ergebnis ist kuerzer als erwartet!")
                ui.plain(f"   Erwartet:     {format_material_len(expected_output)}"
                         f"  ({expected_output:.1f}s)")
                ui.plain(f"   Tatsaechlich: {format_material_len(actual)}"
                         f"  ({actual:.1f}s)")
                ui.plain(f"   Fehlend:      {format_material_len(diff)}  ({diff:.1f}s)")
                self.logger.log(
                    f"WARNUNG: Ausgabe kuerzer als erwartet! Erwartet "
                    f"{expected_output:.1f}s, erhalten {actual:.1f}s, "
                    f"Differenz {diff:.1f}s", "WARNING")

                ui.detail("Stream-Uebersicht der Quelldateien (Details im Log):")
                for f in files:
                    summary = self.ffmpeg.get_stream_summary(str(f))
                    ui.detail(f"  {f.name}: {summary}")
                    self.logger.log(f"Stream-Uebersicht {f.name}: {summary}")
            else:
                ui.ok(f"Vollstaendigkeit geprueft: {format_material_len(actual)} "
                      f"aus {len(files)} Dateien")
                self.logger.log(
                    f"Ausgabe vollstaendig: erwartet {expected_output:.1f}s, "
                    f"erhalten {actual:.1f}s (Differenz {diff:.1f}s)")

        self.logger.log(f"Finalvideo erstellt: {output_path}")
        return is_complete, render_time

    # -- Upload / Abschluss ------------------------------------------------

    def upload_video(self, video_path: Path, title: str, description: str,
                     recording_date: str, custom_tags: str = "",
                     privacy_override: Optional[str] = None) -> Tuple[str, float]:
        video_id, upload_time = self.uploader.upload_video(
            video_path, title, description, recording_date, custom_tags, privacy_override)
        self.uploader.add_to_playlist(video_id)
        return video_id, upload_time

    def finalize_after_upload(self, video_path: Path, video_id: str, title: str,
                              privacy: str = "",
                              archive: bool = True) -> Optional[Path]:
        """Schreibt den Marker und archiviert - mit sauberer Fehlertrennung.

        Ein Fehler beim Marker darf nicht als 'Upload fehlgeschlagen'
        gemeldet werden: das Video ist dann bereits auf YouTube und wuerde
        beim naechsten Start ein zweites Mal hochgeladen. Ebenso wird der
        Rueckgabewert der Archivierung ausgewertet, statt blind Erfolg zu
        melden.

        archive=False: Liegt die Datei bereits im Archiv, waere ein
        Verschieben sinnlos - der Marker wird dann nur aktualisiert.
        """
        try:
            self.marker.write_marker(video_path, video_id, title, privacy)
        except Exception as exc:
            self.logger.log(f"Uploadmarker nicht schreibbar (Upload war erfolgreich!): "
                            f"{exc}", "ERROR")
            ui.plain()
            ui.warn(f"Uploadmarker konnte nicht geschrieben werden: {exc}")
            ui.plain(f"   Das Video IST auf YouTube (ID: {video_id}).")
            ui.plain("   Ohne Marker wird es beim naechsten Start erneut als offener")
            ui.plain("   Upload angeboten - dann bitte NICHT erneut hochladen.")
            return None

        if not archive:
            return video_path.parent

        try:
            success, target = self.archiver.archive_with_retry(video_path)
        except Exception as exc:
            self.logger.log(f"Archivierung fehlgeschlagen (Upload war erfolgreich!): "
                            f"{exc}", "ERROR")
            ui.warn(f"Archivierung fehlgeschlagen: {exc}")
            ui.plain(f"   Das Video liegt weiterhin in: {video_path}")
            return None

        if success:
            return target

        ui.warn("Archivierung fehlgeschlagen (Upload war erfolgreich).")
        ui.plain(f"   Das Video liegt weiterhin in: {video_path}")
        ui.detail("Haeufigste Ursache: Die Datei ist noch in einem Player geoeffnet.")
        return None

    def find_pending_uploads(self) -> List[Path]:
        """Gerenderte Videos ohne gueltigen Uploadmarker."""
        if not self.cfg.output_dir.exists():
            return []
        videos = [f for f in self.cfg.output_dir.iterdir()
                  if f.is_file() and f.suffix.lower() == ".mp4"]
        videos.sort(key=lambda f: f.stat().st_mtime)
        pending = [v for v in videos if self.marker.read_marker(v) is None]
        if pending:
            self.logger.log(f"{len(pending)} offene(r) Upload(s) gefunden")
        return pending

    # -- Aufnahmedatum -----------------------------------------------------

    def get_recording_date_from_folder(self, folder: Path) -> Optional[str]:
        if not folder.exists():
            return None
        mp4_files = self._sorted_mp4(folder)
        if not mp4_files:
            return None
        date = self.ffmpeg.get_creation_time(str(mp4_files[0]))
        if date:
            self.logger.log(f"Aufnahmedatum aus Metadaten: {mp4_files[0].name} -> {date}")
        return date

    def guess_recording_date(self, video_path: Path) -> str:
        """Ermittelt das Aufnahmedatum eines fertigen Videos.

        Reihenfolge: Datum im Dateinamen -> Metadaten des Quellordners ->
        Datei-Zeitstempel als letzte Rueckfallebene.
        """
        match = re.match(r"(\d{4}-\d{2}-\d{2})", video_path.stem)
        if match:
            return match.group(1)

        folder = self._source_folder_for_video(video_path)
        if folder:
            date = self.get_recording_date_from_folder(folder)
            if date:
                return date

        self.logger.log(f"Kein Aufnahmedatum fuer {video_path.name} ermittelbar - "
                        "verwende Datei-Zeitstempel", "WARNING")
        return datetime.fromtimestamp(video_path.stat().st_mtime).strftime("%Y-%m-%d")

    def derive_recording_date_from_folder(self, folder: Path) -> str:
        match = re.match(r"(\d{4}-\d{2}-\d{2})", folder.name)
        if match:
            return match.group(1)

        date = self.get_recording_date_from_folder(folder)
        if date:
            return date

        mp4_files = self._sorted_mp4(folder)
        if mp4_files:
            self.logger.log("Kein Aufnahmedatum in den Metadaten - verwende "
                            "Datei-Zeitstempel (kann das Kopierdatum sein)", "WARNING")
            return datetime.fromtimestamp(
                mp4_files[0].stat().st_mtime).strftime("%Y-%m-%d")

        return datetime.now().strftime("%Y-%m-%d")

    # -- Resume ------------------------------------------------------------

    def resume_pending_uploads(self, pending: List[Path]) -> None:
        """Laedt bereits gerenderte Videos hoch, ohne neu zu rendern."""
        for video_path in pending:
            if not video_path.exists():
                self.logger.log(f"Video verschwunden: {video_path}", "WARNING")
                continue

            ui.section(f"Upload nachholen: {video_path.name}", "up")

            recording_date = self.guess_recording_date(video_path)
            span = self.get_source_span_for_video(video_path)
            period_str = format_h_min(span) if span else ""

            title, description, custom_tags, recording_date, privacy = \
                self.menu.get_job_details(recording_date, period_str)

            problems = validate_youtube_metadata(
                title, description, self.uploader.build_tag_list(custom_tags))
            if problems:
                ui.error("Die Metadaten verletzen YouTube-Limits:")
                for problem in problems:
                    ui.plain(f"   - {problem}")
                ui.plain(f"   {video_path.name} wird uebersprungen.")
                self.logger.log(f"Resume uebersprungen (Metadaten): {problems}", "ERROR")
                continue

            ui.plain()
            try:
                video_id, _ = self.upload_video(video_path, title, description,
                                                recording_date, custom_tags,
                                                privacy_override=privacy)
            except Exception as exc:
                self.logger.log(f"Resume-Upload fehlgeschlagen fuer "
                                f"{video_path.name}: {exc}", "ERROR")
                ui.error(f"Upload fehlgeschlagen: {exc}")
                ui.plain(f"   Video bleibt in: {video_path}")
                continue

            self.finalize_after_upload(video_path, video_id, title,
                                       privacy or self.cfg.yt_privacy)
            ui.ok(f"Fertig - https://youtu.be/{video_id}")
            self.logger.log(f"Resume-Upload abgeschlossen: {video_path.name} -> {video_id}")

    # -- Uploadmodus -------------------------------------------------------

    def collect_upload_candidates(self) -> List[Dict[str, Any]]:
        """Sammelt alle hochladbaren Videos aus Archiv- UND Ausgabeordner.

        Im Archiv liegen bereits hochgeladene Videos, im Ausgabeordner die
        noch offenen - beide gemeinsam zu zeigen erspart einen zweiten
        Programmlauf.
        """
        candidates: List[Dict[str, Any]] = []

        sources = [
            (self.cfg.archiv_dir, "Archiv", "A"),
            (self.cfg.output_dir, "Ausgabe", "O"),
        ]

        seen: set = set()

        for directory, origin, short in sources:
            if not directory.exists():
                self.logger.log(f"{origin}-Ordner existiert nicht: {directory}", "WARNING")
                continue

            for path in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
                if not path.is_file() or path.suffix.lower() != ".mp4":
                    continue

                resolved = path.resolve()
                if resolved in seen:
                    # Archiv und Ausgabe koennen auf denselben Ordner zeigen.
                    continue
                seen.add(resolved)

                stat = path.stat()
                candidates.append({
                    "path": path,
                    "origin": origin,
                    "origin_short": short,
                    "in_archive": origin == "Archiv",
                    "size_mb": stat.st_size / (1024 * 1024),
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                    "mtime_raw": stat.st_mtime,
                    "marker": self.marker.read_marker(path),
                })

        # Neueste zuerst - das entspricht der Erwartung beim Nacharbeiten.
        candidates.sort(key=lambda entry: entry["mtime_raw"], reverse=True)

        self.logger.log(f"{len(candidates)} Video(s) fuer den Uploadmodus gefunden")
        return candidates

    def prepare_batch_entries(self, selected: List[Dict[str, Any]],
                              template_data: Dict[str, str],
                              privacy: str) -> List[Dict[str, Any]]:
        """Reichert die Auswahl mit Titel, Beschreibung und Tags an.

        Der Titel entsteht je Video aus dem Datum des Videos und dem
        Titeltext der Vorlage - so bleiben die Videos unterscheidbar, ohne
        dass pro Datei etwas eingetippt werden muss.
        """
        template_title = (template_data.get("title") or "").strip()
        template_body = template_data.get("description", "")
        template_tags = template_data.get("tags", "")

        entries: List[Dict[str, Any]] = []

        for entry in selected:
            video_path = entry["path"]
            recording_date = self.guess_recording_date(video_path)

            # Wanduhrzeit nur, wenn der Quellordner noch existiert.
            span = self.get_source_span_for_video(video_path)
            period_str = format_h_min(span) if span else ""

            if template_title:
                if re.match(r"^\d{4}-\d{2}-\d{2}", template_title):
                    # Vorlage bringt bereits ein Datum mit - unveraendert nutzen.
                    title = template_title
                else:
                    title = f"{recording_date} - {template_title}"
            else:
                title = f"{recording_date} - Time-Lapse"

            description = build_description(recording_date, template_body, period_str)

            entries.append({
                **entry,
                "recording_date": recording_date,
                "period_str": period_str,
                "title": title,
                "description": description,
                "tags": template_tags,
                "privacy": privacy,
            })

        return entries

    def run_batch_upload(self, entries: List[Dict[str, Any]],
                         dry_run: bool = False) -> Dict[str, List[str]]:
        """Arbeitet den Stapel ab. Rueckgabe: Bilanz nach Kategorie.

        Ein Fehler beendet nicht den Stapel, sondern ueberspringt die
        betroffene Datei. Am Ende steht eine Bilanz.
        """
        result: Dict[str, List[str]] = {
            "erfolg": [], "uebersprungen": [], "fehler": [],
        }

        total = len(entries)

        for number, entry in enumerate(entries, 1):
            video_path = entry["path"]
            ui.section(f"[{number}/{total}] {video_path.name}", "up")

            if not video_path.exists():
                ui.warn("Datei ist nicht mehr vorhanden - wird uebersprungen.")
                self.logger.log(f"Datei verschwunden: {video_path}", "WARNING")
                result["uebersprungen"].append(f"{video_path.name} (nicht mehr vorhanden)")
                continue

            ui.kv("Titel", entry["title"], 16)
            ui.kv("Aufnahmedatum", entry["recording_date"], 16)
            if entry["period_str"]:
                ui.kv("Aufnahmezeitraum", entry["period_str"], 16)
            ui.kv("Sichtbarkeit", entry["privacy"], 16)

            # Metadaten VOR dem Upload pruefen - ein zu langer Titel wuerde
            # sonst erst nach der kompletten Uebertragung als HTTP 400 auffallen.
            problems = validate_youtube_metadata(
                entry["title"], entry["description"],
                self.uploader.build_tag_list(entry["tags"]))
            if problems:
                ui.error("Metadaten verletzen YouTube-Limits:")
                for problem in problems:
                    ui.plain(f"   - {problem}")
                ui.plain("   Wird uebersprungen.")
                self.logger.log(f"Uebersprungen (Metadaten) {video_path.name}: {problems}",
                                "ERROR")
                result["uebersprungen"].append(f"{video_path.name} (Metadaten)")
                continue

            if dry_run:
                ui.info("Trockenlauf - kein Upload, keine Aenderung.")
                ui.detail(f"Beschreibung ({len(entry['description'])} Zeichen), "
                          f"erste Zeile: {entry['description'].splitlines()[0]}")
                result["erfolg"].append(f"{video_path.name} (Trockenlauf)")
                continue

            ui.plain()
            try:
                video_id, _ = self.upload_video(
                    video_path, entry["title"], entry["description"],
                    entry["recording_date"], entry["tags"],
                    privacy_override=entry["privacy"])
            except Exception as exc:
                self.logger.log(f"Upload fehlgeschlagen fuer {video_path.name}: {exc}",
                                "ERROR")
                ui.error(f"Upload fehlgeschlagen: {exc}")
                ui.detail("Die Datei bleibt unveraendert liegen, der Stapel laeuft weiter.")
                result["fehler"].append(f"{video_path.name}: {exc}")
                continue

            # Aus dem Archiv heraus wird nicht noch einmal archiviert.
            self.finalize_after_upload(video_path, video_id, entry["title"],
                                       entry["privacy"],
                                       archive=not entry["in_archive"])

            ui.ok(f"https://youtu.be/{video_id}")
            result["erfolg"].append(f"{video_path.name} -> {video_id}")
            self.logger.log(f"Stapel-Upload erfolgreich: {video_path.name} -> {video_id}")

        return result


# ============================================================================
# Start- und Abschlussausgaben
# ============================================================================

def show_banner(mode: str = "") -> None:
    ui.plain()
    ui.rule("=")
    title = f" {ui.sym('film')} GoPro Time-Lapse Processor   v{__VERSION__}"
    if mode:
        title += f"   [{mode}]"
    ui.plain(ui._c(title, ui._BOLD))
    ui.rule("=")


def show_config_summary(config: Config, upload_mode: bool = False) -> None:
    ui.plain(f"   Konfiguration: {config.path.name}")
    if not upload_mode:
        ui.plain(f"   Aufnahmen:     {config.aufnahmen_dir}")
    ui.plain(f"   Ausgabe:       {config.output_dir}")
    ui.plain(f"   Archiv:        {config.archiv_dir}")
    ui.plain(f"   Sichtbarkeit:  {config.yt_privacy}")
    ui.plain()


def ensure_external_tools() -> None:
    """Prueft ffmpeg und ffprobe VOR allem anderen.

    Fehlte FFmpeg im PATH, schlugen bisher alle Encoder-Tests still fehl,
    es wurde 'libx264' gemeldet, und der eigentliche Fehler tauchte erst
    beim Render auf - mit irrefuehrender Meldung.
    """
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        ui.plain()
        ui.error(f"{' und '.join(missing)} wurde(n) nicht gefunden.")
        ui.plain("   FFmpeg muss installiert und ueber PATH erreichbar sein.")
        ui.plain("   Download: https://ffmpeg.org/download.html")
        ui.plain("   Test:     ffmpeg -version")
        sys.exit(1)


def show_final_summary(video_id: str, title: str, source_str: str, result_str: str,
                       file_count: int, render_time: float, upload_time: float,
                       archive_path: Optional[Path], render_complete: bool,
                       fps_saved: bool, fps: int, logger: Logger) -> None:
    """Kompakte Abschlussuebersicht mit anklickbarem YouTube-Link."""
    ui.header("Verarbeitung abgeschlossen", "ok")
    ui.kv("Titel", title)
    ui.kv("YouTube", f"https://youtu.be/{video_id}")
    ui.plain()
    ui.kv("Quellmaterial", f"{source_str}  ({file_count} Dateien)")
    ui.kv("Ergebnis", result_str)
    ui.kv("Renderzeit", format_hms(render_time))
    ui.kv("Uploadzeit", format_hms(upload_time))
    if archive_path:
        ui.kv("Archiviert", archive_path)
    if fps_saved:
        ui.plain()
        ui.detail(f"Ziel-FPS {fps} wurde als Vorbelegung gespeichert.")

    if logger.warnings:
        ui.plain()
        ui.warn(f"{len(logger.warnings)} Warnung(en) waehrend des Laufs "
                "- Details in der Logdatei:")
        ui.detail(str(logger.log_file))

    if not render_complete:
        ui.plain()
        ui.rule("=")
        ui.warn("ACHTUNG: Das Ergebnis ist kuerzer als erwartet - es wurde")
        ui.plain("   moeglicherweise nicht das gesamte Quellmaterial uebernommen!")

    ui.rule("=")


def show_batch_summary(result: Dict[str, List[str]], elapsed: float,
                       dry_run: bool, logger: Logger) -> None:
    """Bilanz des Stapel-Uploads."""
    ui.header("Stapel-Upload abgeschlossen" + (" (Trockenlauf)" if dry_run else ""),
              "test" if dry_run else "ok")

    ui.kv("Erfolgreich", len(result["erfolg"]), 18)
    ui.kv("Uebersprungen", len(result["uebersprungen"]), 18)
    ui.kv("Fehlgeschlagen", len(result["fehler"]), 18)
    ui.kv("Gesamtdauer", format_hms(elapsed), 18)

    if result["erfolg"]:
        ui.plain()
        ui.plain(f"  {ui._c('Erfolgreich', ui._BOLD)}")
        for item in result["erfolg"]:
            if " -> " in item:
                name, video_id = item.split(" -> ", 1)
                ui.plain(f"   {ui.sym('ok')} {name}")
                ui.detail(f"https://youtu.be/{video_id}")
            else:
                ui.plain(f"   {ui.sym('ok')} {item}")

    if result["uebersprungen"]:
        ui.plain()
        ui.plain(f"  {ui._c('Uebersprungen', ui._BOLD)}")
        for item in result["uebersprungen"]:
            ui.plain(f"   - {item}")

    if result["fehler"]:
        ui.plain()
        ui.plain(f"  {ui._c('Fehlgeschlagen', ui._BOLD)}")
        for item in result["fehler"]:
            ui.plain(f"   {ui.sym('err')} {item}")
        ui.plain()
        ui.detail("Die betroffenen Dateien wurden nicht veraendert und koennen "
                  "erneut gewaehlt werden.")

    ui.plain()
    ui.detail(f"Logdatei: {logger.log_file}")
    ui.rule("=")


# ============================================================================
# Ablauf: Uploadmodus (-u)
# ============================================================================

def run_upload_mode(config: Config, options: Options) -> None:
    """Stapel-Upload fertiger Videos aus Archiv- und Ausgabeordner."""
    show_banner("Uploadmodus" + (" / Trockenlauf" if options.dry_run else ""))
    show_config_summary(config, upload_mode=True)

    if options.dry_run:
        ui.info("Trockenlauf: Es wird nichts hochgeladen, verschoben oder geschrieben.")

    processor = GoProTimeLapseProcessor(config, upload_only=True)

    # ---- 1. Kandidaten sammeln -------------------------------------------
    candidates = processor.collect_upload_candidates()
    if not candidates:
        ui.plain()
        ui.warn("Keine Videos gefunden.")
        ui.plain("   Durchsucht wurden:")
        ui.plain(f"     {config.archiv_dir}")
        ui.plain(f"     {config.output_dir}")
        return

    selected = processor.menu.select_upload_candidates(candidates)
    if not selected:
        ui.plain()
        ui.plain("   Abgebrochen.")
        return

    # ---- 2. Re-Upload bestaetigen ----------------------------------------
    already = [entry for entry in selected if entry["marker"]]
    if already and not options.dry_run:
        if not processor.menu.confirm_reupload(already):
            # Nur die noch nicht hochgeladenen weiterverarbeiten.
            selected = [entry for entry in selected if not entry["marker"]]
            if not selected:
                ui.plain()
                ui.plain("   Nichts mehr zu tun - abgebrochen.")
                return
            ui.info(f"Es werden nur die {len(selected)} noch nicht hochgeladenen "
                    "Videos verarbeitet.")

    # ---- 3. Beschreibungs-Vorlage (einmal fuer den Stapel) ---------------
    ui.section("Beschreibung fuer den gesamten Stapel", "note")
    templates = processor.template_manager.find_templates()
    if not templates:
        ui.error("Keine Beschreibungs-Vorlage gefunden.")
        ui.plain(f"   Erwartet in: {config.beschreibung_dir}")
        ui.plain("   Namensschema: '<name>-beschreibung.md' oder '<name>_beschreibung.md'")
        ui.detail("Der Uploadmodus braucht eine Vorlage, da Titel und Beschreibung "
                  "fuer alle Videos gemeinsam gelten.")
        return

    chosen = processor.menu.select_beschreibung_template(templates, allow_manual=False)
    template_data = processor.template_manager.parse(chosen)
    if not template_data:
        ui.error(f"{chosen.name} enthaelt keine erkennbaren Abschnitte.")
        ui.detail("Erwartet werden '# Titel', '# Beschreibung', '# Tags'.")
        return

    ui.ok(f"Vorlage: {chosen.name}")
    for key, value in template_data.items():
        preview = value.replace("\n", " ")
        if len(preview) > 70:
            preview = preview[:67] + "..."
        ui.detail(f"{key}: {preview}")

    # ---- 4. Sichtbarkeit (einmal fuer den Stapel) ------------------------
    default_privacy = template_data.get("privacy_status") or config.yt_privacy
    privacy = processor.menu.select_batch_privacy(default_privacy)

    # ---- 5. Vorbereiten und bestaetigen ----------------------------------
    entries = processor.prepare_batch_entries(selected, template_data, privacy)

    if not processor.menu.confirm_batch(entries, chosen.name, privacy, options.dry_run):
        ui.plain()
        ui.plain("   Abgebrochen.")
        processor.logger.log("Stapel-Upload vom Benutzer abgebrochen")
        return

    # ---- 6. Abarbeiten ---------------------------------------------------
    start = time.time()
    result = processor.run_batch_upload(entries, dry_run=options.dry_run)
    show_batch_summary(result, time.time() - start, options.dry_run, processor.logger)


# ============================================================================
# Ablauf: Vollstaendige Verarbeitung (ohne Argumente)
# ============================================================================

TOTAL_STEPS = 8


def run_full_mode(config: Config, options: Options) -> None:
    """Vollstaendiger Ablauf: Aufnahme waehlen, rendern, hochladen."""
    show_banner("Trockenlauf" if options.dry_run else "")
    show_config_summary(config)

    if options.dry_run:
        ui.warn("--dry-run wirkt nur im Uploadmodus (-u) und wird hier ignoriert.")

    processor = GoProTimeLapseProcessor(config)

    # ---- Offene Uploads zuerst -------------------------------------------
    pending = processor.find_pending_uploads()
    if pending:
        selected = processor.menu.show_pending_uploads(pending)
        if selected:
            processor.resume_pending_uploads(selected)
            if not processor.menu.confirm_continue_with_new_job():
                ui.plain()
                ui.plain(f"{ui.sym('wave')} Programm wird beendet.")
                return

    # ---- 1. Aufnahme waehlen ---------------------------------------------
    ui.step(1, TOTAL_STEPS, "Aufnahme waehlen")
    recordings = processor.list_recordings()
    if not recordings:
        processor.logger.error_and_exit(
            f"Keine Aufnahmen gefunden in: {config.aufnahmen_dir}")

    folder_name = processor.menu.show_recording_list(recordings)
    folder = processor.select_recording(folder_name)
    record = next(r for r in recordings if r["name"] == folder_name)
    span_seconds = record["span_seconds"]
    span_ratio = record.get("span_ratio")

    # Kollisionspruefung bewusst frueh - es waere aergerlich, erst nach der
    # kompletten Faktor-Testschleife zu erfahren, dass abgebrochen wird.
    output_path = config.output_dir / f"{folder_name}_final.mp4"
    if output_path.exists():
        existing = processor.marker.read_marker(output_path)
        if existing:
            ui.info(f"Ein bereits hochgeladenes Video dieses Namens wird "
                    f"ueberschrieben (ID: {existing.get('youtube_video_id')}).")
        elif not processor.menu.confirm_overwrite(output_path):
            ui.plain()
            ui.plain("   Abgebrochen. Das vorhandene Video wurde nicht angetastet.")
            ui.detail("Beim naechsten Start kannst du es unter 'Offene Uploads' "
                      "hochladen - oder mit '-u'.")
            return

    # ---- 2. Umfang -------------------------------------------------------
    ui.step(2, TOTAL_STEPS, "Umfang der Aufnahme")
    source_seconds = processor.get_total_source_duration(folder)
    source_str = format_material_len(source_seconds) if source_seconds > 0 else ""
    period_str = format_span(span_seconds)

    ui.kv("Zeitraum (Wanduhr)", period_str, 28)
    if source_str:
        ui.kv("Laenge Videomaterial", source_str, 28)
        if span_ratio:
            ui.kv("Zeitraffer der Kamera", f"ca. {span_ratio:.0f}x", 28)
            ui.detail("Die Kamera hat beim Aufnehmen bereits gerafft - das "
                      "Videomaterial ist deshalb viel kuerzer als der Zeitraum.")
        elif span_seconds <= 0:
            ui.detail("Der Aufnahmezeitraum laesst sich bei nur einer Datei nicht "
                      "bestimmen und entfaellt in der Beschreibung.")
    else:
        ui.warn("Laenge des Videomaterials konnte nicht ermittelt werden.")

    # ---- 3. Erste Vorschau -----------------------------------------------
    ui.step(3, TOTAL_STEPS, "Erste Vorschau des Rohmaterials")
    processor.preview_first_clip(folder)

    # ---- 4. Einstellungen ------------------------------------------------
    ui.step(4, TOTAL_STEPS, "Einstellungen")
    target_fps = processor.menu.get_target_fps()
    preview_duration = processor.menu.get_test_preview_duration()

    # ---- 5. Faktor testen ------------------------------------------------
    ui.step(5, TOTAL_STEPS, "Geschwindigkeitsfaktor testen")
    while True:
        factor = processor.menu.get_speed_factor(source_seconds)
        ui.plain()
        processor.render_preview(folder, factor, target_fps, preview_duration)
        if processor.menu.confirm_preview():
            break
        ui.plain("   Neuer Versuch mit anderem Faktor...")

    processor.cleanup_preview_temp_files()

    # ---- 6. Job-Details --------------------------------------------------
    ui.step(6, TOTAL_STEPS, "Titel, Beschreibung und Tags")
    recording_date = processor.derive_recording_date_from_folder(folder)
    # In die Beschreibung geht die WANDUHRZEIT, nicht die Materiallaenge.
    # Bei fehlender Datenbasis wird nichts eingesetzt (Zeile entfaellt).
    description_period = format_h_min(span_seconds) if span_seconds > 0 else ""
    title, description, custom_tags, recording_date, privacy = \
        processor.menu.get_job_details(recording_date, description_period)

    # YouTube-Limits VOR dem Render pruefen - sonst faellt ein zu langer
    # Titel erst nach Stunden Renderzeit als HTTP 400 auf.
    problems = validate_youtube_metadata(
        title, description, processor.uploader.build_tag_list(custom_tags))
    if problems:
        ui.plain()
        ui.error("Die Metadaten verletzen YouTube-Limits:")
        for problem in problems:
            ui.plain(f"   - {problem}")
        ui.plain()
        ui.plain("   Bitte kuerzen und das Skript erneut starten.")
        ui.detail("Die Pruefung erfolgt vor dem Render, damit keine Renderzeit "
                  "verloren geht.")
        processor.logger.log(f"Abbruch wegen YouTube-Limits: {problems}", "ERROR")
        return

    # ---- 7. Bestaetigung -------------------------------------------------
    reference = source_seconds if source_seconds > 0 else span_seconds
    expected_result = reference / factor if reference > 0 else 0.0

    confirmed = processor.menu.confirm_job([
        ("Material", [
            ("Aufnahme", folder_name),
            ("Quelldateien", f"{record['file_count']} MP4-Dateien"),
            ("Zeitraum (Wanduhr)", period_str),
            ("Laenge Videomaterial", source_str or "unbekannt"),
        ]),
        ("Rendern", [
            ("Geschwindigkeitsfaktor", factor),
            ("Ziel-Framerate", f"{target_fps} FPS"),
            ("Laenge Finalvideo", format_material_len(expected_result)),
            ("Encoder", processor.ffmpeg.profile["label"]),
            ("Qualitaet / Tempo", f"{config.qualitaet} / {config.tempo}"),
        ]),
        ("Veroeffentlichung", [
            ("Titel", title),
            ("Sichtbarkeit", privacy or config.yt_privacy),
            ("Playlist", config.yt_playlist_id or "(keine)"),
            ("Ausgabe", config.output_dir),
        ]),
    ])

    if not confirmed:
        processor.logger.log("Auftrag vom Benutzer abgebrochen")
        ui.plain()
        ui.plain("   Auftrag abgebrochen.")
        return

    # ---- 8. Rendern, hochladen, archivieren ------------------------------
    ui.step(7, TOTAL_STEPS, "Finalrender")
    render_complete, render_time = processor.render_final(
        folder, factor, target_fps, output_path, source_seconds)

    ui.step(8, TOTAL_STEPS, "YouTube-Upload")
    try:
        video_id, upload_time = processor.upload_video(
            output_path, title, description, recording_date, custom_tags,
            privacy_override=privacy)
    except Exception as exc:
        processor.logger.log(f"Upload fehlgeschlagen: {exc}", "ERROR")
        ui.plain()
        ui.error(f"Upload fehlgeschlagen: {exc}")
        ui.plain(f"   Das Video bleibt in: {output_path}")
        ui.detail("Beim naechsten Start wird es als offener Upload erkannt - "
                  "oder mit '-u' nachholbar.")
        return

    archive_path = processor.finalize_after_upload(
        output_path, video_id, title, privacy or config.yt_privacy)

    # Ziel-FPS erst NACH dem vollstaendig erfolgreichen Lauf speichern -
    # ein abgebrochener Testlauf soll die Vorbelegung nicht ueberschreiben.
    fps_saved = config.save_ziel_fps(target_fps, processor.logger)

    processor.logger.log("Verarbeitung abgeschlossen")
    show_final_summary(
        video_id=video_id,
        title=title,
        source_str=source_str or "unbekannt",
        result_str=format_material_len(expected_result),
        file_count=record["file_count"],
        render_time=render_time,
        upload_time=upload_time,
        archive_path=archive_path,
        render_complete=render_complete,
        fps_saved=fps_saved,
        fps=target_fps,
        logger=processor.logger,
    )


# ============================================================================
# Einstieg
# ============================================================================

def main() -> None:
    options = parse_arguments(sys.argv[1:])

    config = load_configuration()
    ensure_external_tools()

    if options.upload_mode:
        run_upload_mode(config, options)
    else:
        run_full_mode(config, options)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        ui.plain()
        ui.plain()
        ui.plain(f"{ui.sym('wave')} Abbruch durch Benutzer (Strg+C).")
        sys.exit(0)
