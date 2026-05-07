# Fishbot (Windows)

AFK fishing bot for Roblox **Bridger: WESTERN** on Windows 10/11. This is the
Windows-native port of the Linux/Sway version at `~/projects/fishingscript/`.
Vision pipeline (hook/fish/chest detection + QTE OCR) is identical; only the
I/O layer is rewritten for the Win32 stack.

---

## For end users — installing the bot

1. Download `fishbot-setup-1.0.0.exe`.
2. Double-click it. The installer runs **without admin/UAC** and installs to
   `%LOCALAPPDATA%\Programs\Fishbot`. Optional desktop shortcut is opt-in.
3. Launch **Fishbot** from the Start Menu.
4. With Roblox + the Bridger game already running, click **Calibrate…**, drag
   a rectangle over the water where you want the bot to cast, then click
   **Start**.

### Uninstalling

Open **Settings → Apps → Installed apps**, find **Fishbot**, click **Uninstall**.
The uninstaller removes:

- the install directory (`%LOCALAPPDATA%\Programs\Fishbot`),
- Start Menu and (if created) desktop shortcuts,
- the runtime data directory (`%LOCALAPPDATA%\Fishbot` — debug frames, logs).

Your edited config at `%APPDATA%\Fishbot\config.toml` is **kept** so a
reinstall preserves your settings. Delete that folder by hand if you want a
fully clean removal.

### What the installer does NOT do

- No registry entries outside the standard per-user uninstall key.
- No services, scheduled tasks, autostart entries, or PATH modifications.
- No firewall rules.
- No telemetry, no auto-updater, no admin prompts.

You can verify with PowerShell:

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -like '*fishbot*' }
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" 2>$null | Select-String fishbot
Get-NetFirewallRule | Where-Object { $_.DisplayName -like '*fishbot*' }
```

All three should return nothing.

### First-run SmartScreen

Because the installer is not code-signed, Windows SmartScreen will warn the
first time you run it ("unrecognised app"). Click **More info → Run anyway**.
This is the standard behaviour for unsigned freeware.

---

## For developers — running from source

Requires Python 3.12+ and Tesseract OCR on PATH (or in the bundled
`installer/vendor/tesseract/` folder).

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[build]"

# Smoke test — imports + synthetic A-Z OCR check
python -m tests.test_smoke

# Run the GUI
python -m fishbot.gui

# Run the bot CLI directly
python -m fishbot.main --debug-mask -v
```

`scripts\run.bat` and `scripts\run-gui.bat` are dev-mode shortcuts for the
above.

### Building the one-shot bootstrap installer

A small (~10 MB) `.exe` that, on first run, downloads everything needed
(Python embeddable, pip, Tesseract, fishbot source) into
`%LOCALAPPDATA%\Fishbot`, then launches the GUI. Idempotent: re-running it
just relaunches the GUI.

Prerequisites: Python 3.12+ on PATH. No Inno Setup, no Tesseract download,
no PyQt6 needed on the build machine — the heavy bits are fetched at
install time on the user's box.

```powershell
$env:FISHBOT_SOURCE_URL = "https://github.com/<user>/fishbot-windows/archive/refs/tags/v1.0.0.zip"
powershell -ExecutionPolicy Bypass -File installer\build-bootstrap.ps1
```

Output: `dist\fishbot-setup.exe`. Ship that single file.

### Building the full (offline) installer

Prerequisites on the build machine:

1. Python 3.12+ on PATH.
2. **Inno Setup 6** installed (https://jrsoftware.org/isinfo.php).
3. Bundled Tesseract:
   - Download the UB-Mannheim portable build:
     https://github.com/UB-Mannheim/tesseract/wiki
   - Extract `tesseract.exe` and `tessdata/eng.traineddata` into
     `installer/vendor/tesseract/`. Other language files can be deleted to
     keep the installer small.

Then:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

Output: `dist\fishbot-setup-1.0.0.exe`.

---

## Project layout

```
fishbot-windows/
├── pyproject.toml
├── config.toml                 # default config shipped with the installer
├── README.md
├── src/fishbot/
│   ├── main.py                 # state machine
│   ├── gui.py                  # PyQt6 GUI
│   ├── inputs.py               # pydirectinput
│   ├── window.py               # pywin32 + psutil
│   ├── capture.py              # mss
│   ├── calibrate.py            # PyQt6 overlay region picker
│   ├── paths.py                # %APPDATA% / %LOCALAPPDATA% resolver
│   ├── qte.py                  # OCR (unchanged from Linux version)
│   ├── vision.py               # detection (unchanged)
│   └── sample_hsv.py           # debug helper (unchanged)
├── scripts/
│   ├── run.bat
│   └── run-gui.bat
├── installer/
│   ├── fishbot.iss             # Inno Setup script (offline installer)
│   ├── build.ps1               # offline-installer build pipeline
│   ├── fishbot.spec            # PyInstaller spec — CLI exe
│   ├── fishbot-gui.spec        # PyInstaller spec — GUI exe
│   ├── bootstrap.py            # one-shot network bootstrap installer
│   ├── bootstrap.spec          # PyInstaller spec — bootstrap exe
│   ├── build-bootstrap.ps1     # bootstrap-installer build pipeline
│   └── vendor/tesseract/       # populated by the maintainer, gitignored
└── tests/
    └── test_smoke.py
```

## Runtime data layout

| Path                                      | Purpose                              |
|-------------------------------------------|--------------------------------------|
| `%LOCALAPPDATA%\Programs\Fishbot\`        | program files (read-only)            |
| `%APPDATA%\Fishbot\config.toml`           | editable config (survives reinstall) |
| `%LOCALAPPDATA%\Fishbot\debug_frames\`    | `--debug-mask` output                |
