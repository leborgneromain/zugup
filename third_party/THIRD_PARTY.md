# Third-party components

ZugUp itself is licensed under the GNU General Public License v3.0 (see `LICENSE`). It uses and may bundle the components below. Licenses and versions come from the installed package metadata when this file was written; check the upstream projects for the authoritative text.

## Chess engine

| Component | License | Notes |
|---|---|---|
| Stockfish 19 | GPL-3.0 | Separate process, bundled in standalone builds. See `stockfish/NOTICE.md`, `stockfish/Copying.txt` and `stockfish/AUTHORS`. |

## Python libraries

| Package | Version | License |
|---|---|---|
| chess (python-chess) | 1.11.2 | GPL-3.0-or-later |
| Flask | 3.1.3 | BSD-3-Clause |
| Werkzeug | 3.1.9 | BSD-3-Clause |
| Jinja2 | 3.1.6 | BSD |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| itsdangerous | 2.2.0 | BSD |
| click | 8.5.0 | BSD-3-Clause |
| blinker | 1.9.0 | MIT |
| pandas | 3.1.0 | BSD-3-Clause |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| python-dateutil | 3.0.0 | BSD and Apache-2.0 (dual) |
| six | 1.17.0 | MIT |
| tzdata | 2026.5 | Apache-2.0 |
| requests | 2.34.2 | Apache-2.0 |
| urllib3 | 2.8.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| charset-normalizer | 3.5.2 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |

Standalone builds also embed the Python interpreter and the PyInstaller bootloader, which carry their own licenses.

## Web assets

| Component | License | Attribution |
|---|---|---|
| cm-chessboard 8.15.4 (code) | MIT | Copyright (c) 2017 Stefan Haack. License text: `src/zugup/web/static/vendor/cm-chessboard/LICENSE`. |
| Chess piece set `standard.svg` | CC BY-SA 3.0 | Pieces by Cburnett and Rfc1394 from Wikimedia Commons, modified by Stefan Haack (shaack). License: https://creativecommons.org/licenses/by-sa/3.0/. Shipped as found in cm-chessboard 8.15.4, not modified by ZugUp. |
