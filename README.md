# GoPro Time-Lapse Vibe-Coding Processor

Automates GoPro time-lapse processing: interactive selection, LRV speed-test preview, full 4K render, YouTube upload with playlist assignment, and archiving. Auto-detects hardware encoders (NVENC/QSV/AMF) and reads recording date from video metadata.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)
![Status](https://img.shields.io/badge/Status-Beta-orange.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20(primary)-lightgrey.svg)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [Description Templates](#description-templates)
- [Output](#output)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Known Limitations](#known-limitations)
- [Roadmap](#roadmap)
- [License](#license)
- [Third-Party Dependencies](#third-party-dependencies)

---

## Overview

This script turns a folder of raw GoPro Hero 5 Black 4K time-lapse footage into a finished, uploaded YouTube video with minimal manual work:

```
Select recording → Preview clip (VLC) → Test speed factor (fast LRV render)
→ Enter title/description/tags → Full-resolution render → YouTube upload
→ Playlist assignment → Archive source files
```

If a YouTube upload fails partway through, the already-rendered video is automatically detected on the next run and can be re-uploaded **without re-rendering**.

**Status:** Beta — the full workflow is implemented and has been hardened through multiple iterations, but automated tests and upload retry/backoff logic are still missing (see [Known Limitations](#known-limitations)).

---

## Features

- 🎬 **Interactive folder-based workflow** — select a recording, preview it, test a speed factor, confirm, done.
- ⚡ **Smart test render** — always uses the *largest* LRV (or MP4) file in the folder to avoid incomplete "false start" clips as the preview source.
- 🚀 **Automatic hardware encoder detection** — probes NVENC (NVIDIA), Quick Sync (Intel), AMF (AMD), and VideoToolbox (macOS) with a real mini test-encode, falling back to `libx264` if none work.
- 📅 **Accurate recording date** — reads the `creation_time` metadata tag embedded in the video file instead of relying on the filesystem timestamp (which can change when files are copied).
- 📄 **Reusable description templates** — pull title, description, tags, recording date, and visibility from Markdown template files instead of retyping them every time.
- 🔁 **Resume-upload** — a failed YouTube upload is detected automatically on the next start and can be retried without re-rendering.
- 📊 **Live progress with elapsed time** — render progress bar shows percentage, elapsed time so far, and ETA.
- 🗂️ **Automatic archiving** — successfully uploaded videos are moved to an archive folder together with a JSON upload marker.

---

## Requirements

| Component | Notes |
|---|---|
| Python | 3.8 or newer |
| FFmpeg + ffprobe | Must be available in `PATH` |
| VLC Media Player | Used for preview playback |
| Google Cloud project | With **YouTube Data API v3** enabled |
| OAuth credentials | Desktop App type, downloaded as `client_secret.json` |

---

## Installation

```bash
# 1. Create a project folder
mkdir GoProProcessor && cd GoProProcessor

# 2. Place the main script and gopro_config.py in this folder
#    (both files MUST live next to each other)

# 3. Create and activate a virtual environment (Windows)
py -3 -m venv .venv
.venv\Scripts\activate

# 4. Install Python dependencies
python -m pip install --upgrade pip
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2

# 5. Verify FFmpeg / ffprobe / VLC
ffmpeg -version
ffprobe -version
vlc --version

# 6. Create the folder structure
mkdir aufnahmen output archiv logs temp beschreibungen

# 7. Fill in gopro_config.py (see Configuration below), then run
python gopro_timelapse_processor.py
```

### Google/YouTube setup

1. Open the Google Cloud Console and create (or select) a project.
2. Enable the **YouTube Data API v3**.
3. Create OAuth credentials of type **Desktop App**.
4. Download the client file and save it as `client_secret.json` in a protected location.
5. Set its path in `YOUTUBE_CLIENT_SECRETS_FILE` in `gopro_config.py`.
6. On the first upload, a browser window opens for OAuth consent; a token file is created automatically afterwards.

---

## Configuration

All settings live in a separate `gopro_config.py` file next to the main script.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `YOUTUBE_CLIENT_SECRETS_FILE` | `str` | — (required) | Path to the OAuth client file |
| `YOUTUBE_TOKEN_FILE` | `str` | — (required) | Path to the auto-generated token file |
| `YOUTUBE_PLAYLIST_ID` | `str` | — (required) | Target playlist for automatic assignment |
| `YOUTUBE_PRIVACY_STATUS` | `str` | — (required) | `"public"` / `"private"` / `"unlisted"` |
| `YOUTUBE_TAGS` | `list[str]` | — (required) | Default tags for every upload |
| `YOUTUBE_CATEGORY_ID` | `str` | — (required) | YouTube category, e.g. `"19"` (Film & Animation) |
| `BASE_DIR` / `OUTPUT_DIR` / `ARCHIVE_DIR` / `LOG_DIR` / `TEMP_DIR` | `str` | empty = relative default | Working directories |
| `BESCHREIBUNG_DIR` | `str` | empty = `./beschreibungen` | Central folder for description templates *(optional)* |
| `FFMPEG_ENCODER` | `str` | `"auto"` | `"auto"` (auto-detect), `"libx264"`, or an explicit hardware encoder name *(optional)* |
| `FFMPEG_PRESET` | `str` | `""` | Encoder preset; valid values depend on the encoder *(optional)* |

> Optional parameters use safe fallbacks if omitted from an older `gopro_config.py` — no error, no manual migration needed.

---

## Quick Start

1. Copy a GoPro recording into a new subfolder under `aufnahmen/`.
2. Start the script.
3. Pick the recording from the menu.
4. Watch the first clip preview, set target FPS and test-render duration, then iterate on the speed factor until satisfied.
5. Enter title/description/tags (manually or from a template) and confirm with `j`.

```
📁 Available recordings (newest first):
  1. 2026-09-20_11-58 | Start: 2026-09-20 11:58 | Duration: 0h 15min
Selection (number): 1
Target FPS (default: 60): 60
Test render duration in seconds (default: 20): 20
Speed factor (e.g. 2.0 for double speed): 7.0
Happy with the preview? (y/n): y
```

Result: `archiv/2026-09-20_11-58_final.mp4`, uploaded to YouTube and assigned to the configured playlist.

---

## Description Templates

Instead of retyping title, description, and tags for every video, drop a Markdown file into the central template folder (`BESCHREIBUNG_DIR`):

Filename: `<any-name>-beschreibung.md` or `<any-name>_beschreibung.md` (subfolders allowed, search is recursive).

```markdown
# Titel
Sunset over Alexanderplatz

# Beschreibung
Time-lapse from an autumn evening at Alexanderplatz.

# Tags
Berlin, Alexanderplatz, Sunset, Autumn

# Aufnahmedatum
2026-09-20

# Sichtbarkeit
unlisted
```

`# Aufnahmedatum` and `# Sichtbarkeit` are optional and override the auto-detected recording date / default privacy status for that single video only. If templates are found, a selection menu always appears (including a "manual entry" option); missing fields in a chosen template are still asked interactively.

---

## Output

| Output | Location | Content |
|---|---|---|
| Final video | `OUTPUT_DIR`, then `ARCHIVE_DIR` | `<recording-folder>_final.mp4` |
| Upload marker | Next to the video, later in the archive | `<recording-folder>_final.mp4.uploaded.json` |
| Log file | `LOG_DIR` | `<YYYYMMDD_HHMMSS>.log` (one per run) |
| Test preview | `TEMP_DIR` | `preview_<N>s.mp4`, deleted after playback |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `gopro_config.py wurde nicht gefunden!` | Config not next to the main script | Place both files in the same folder |
| `VLC nicht gefunden` | VLC missing or not at expected path | Install VLC or add it to `PATH` |
| `FFmpeg Concat fehlgeschlagen` | FFmpeg missing, source corrupted, or incompatible clips | Check `ffmpeg -version`; verify source files |
| `YouTube Client-Datei fehlt` | Wrong `YOUTUBE_CLIENT_SECRETS_FILE` path | Fix the path in `gopro_config.py` |
| Encoder warning: `'...' funktioniert NICHT auf diesem System` | Configured hardware encoder unavailable | Set `FFMPEG_ENCODER = "auto"` or install the correct driver |
| Upload fails | Network/API error | Restart the script — the finished video is auto-detected as a pending upload and can be resumed without re-rendering |

Logs are written to `logs/<YYYYMMDD_HHMMSS>.log` — look for `ERROR` first, then `WARNING`.

---

## Project Structure

```
<BASE_DIR>/
  aufnahmen/          GoPro recording folders (*.MP4, optional *.LRV)
  output/             Rendered videos before upload
  archiv/             Videos + upload markers after successful upload
  logs/               One log file per run
  temp/               Intermediate render files
  beschreibungen/     Description templates (*-beschreibung.md)
```

---

## Known Limitations

- 🔴 No retry/backoff for YouTube API errors (network/quota) — a failed upload must be retried manually via the resume mechanism.
- 🟡 `VLCPlayer` default paths are Windows-only; other platforms require VLC in `PATH`.
- 🟡 No automated test suite yet.
- 🟢 If a video file lacks the `creation_time` metadata tag, the recording date falls back to the filesystem timestamp (logged as a warning).

## Roadmap

- [ ] Exponential backoff for YouTube upload errors
- [ ] pytest suite with mocked FFmpeg/VLC/YouTube calls
- [ ] Cross-platform VLC path detection
- [ ] Batch mode for multiple recording folders in one run

---

## License

This project is licensed under the **MIT License** — see [`LICENSE`](LICENSE) for details.

---

## Third-Party Dependencies

This project's own code is MIT-licensed. It relies on the following external tools and libraries, each under their own license. **None of them are bundled or redistributed with this repository** — they are installed independently by the end user (via `pip` or a system package manager).

| Component | License | Distribution |
|---|---|---|
| [FFmpeg / ffprobe](https://ffmpeg.org/legal.html) | LGPL v2.1+ (GPL v2+ if built with certain optional components, e.g. libx264) | External binary, invoked via `subprocess` |
| [VLC media player](https://www.videolan.org/legal.html) | GPL v2 (player); libVLC core LGPL v2.1+ | External binary, invoked via `subprocess` |
| [google-api-python-client](https://github.com/googleapis/google-api-python-client) | Apache License 2.0 | Python package via `pip` |
| [google-auth-oauthlib](https://github.com/googleapis/google-auth-library-python-oauthlib) | Apache License 2.0 | Python package via `pip` |
| [google-auth-httplib2](https://github.com/googleapis/google-auth-library-python-httplib2) | Apache License 2.0 | Python package via `pip` |

If you redistribute this project together with any of the above tools bundled as binaries, make sure to comply with their respective license terms (e.g. providing license texts and, for GPL/LGPL components, source code or a written offer thereof).
