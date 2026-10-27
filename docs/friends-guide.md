# ZugUp: installation guide

ZugUp analyzes your Lichess and Chess.com games and gives you exercises based on your mistakes. Everything stays on your computer.

The application starts in French. To switch to English, see step 2 of "Using ZugUp". The names in bold below are the English ones.

## Installation

### Mac

1. Unzip `ZugUp-macos-arm64.zip` (double-click the file).
2. Move `ZugUp` to the Applications folder.
3. The first time, **right-click** `ZugUp`, choose **Open**, then **Open** again in the warning window. A plain double-click is refused because the application is not signed by Apple.
4. If your Mac still blocks it: System Settings, Privacy & Security, then **Open Anyway** at the bottom of the page.

This version only works on recent Macs (Apple M1, M2, M3 chip or newer).

### Windows

1. Unzip `ZugUp-windows-amd64.zip` (right-click, **Extract All**).
2. Open the `ZugUp` folder and double-click `ZugUp.exe`.
3. If Windows shows "Windows protected your PC": click **More info**, then **Run anyway**. The application is not signed.

## Using ZugUp

1. Your browser opens on ZugUp. If nothing opens, go to `http://127.0.0.1:8765`.
2. Go to **Réglages** (Settings). Under **Affichage** (Display), pick your **Langue** (Language), French or English, and your theme (dark or light).
3. Under **Accounts**, for Lichess, click **Connect Lichess** and authorize access on the Lichess site. For Chess.com, just type your username.
4. Choose how many games and which speeds to import (bullet, blitz, rapid), then click **Import from Lichess** or **Import from Chess.com**. The analysis can take several minutes.
5. Go to **Training** to redo your mistakes, **Report** to see your weak spots, **Repertoire** for your openings and **Coach** for the plan of the week.

## Quitting

In **Settings**, click **Quit ZugUp**. Closing the tab does not stop the application.

## Where is my data?

- Mac: `~/Library/Application Support/ZugUp`
- Windows: `%APPDATA%\ZugUp`

This folder holds your database and your Lichess token: do not share it with anyone. To erase everything, delete this folder after quitting the application.

## Licenses and source code

ZugUp is free software under the GNU General Public License v3.0. The license texts, the list of third-party components and the source code offer are in the `licenses` folder shipped with the application. The source code is at https://github.com/leborgneromain/zugup, or ask the person who gave you the application.

## If something goes wrong

The `zugup.log` file in the data folder lists the errors. Send it to the person who gave you the application.
