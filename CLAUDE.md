# Fishbot — Claude project notes

Things that aren't obvious from reading the code and that a future agent
needs to avoid relearning the hard way.

## Platform

This is a **Windows-only runtime** developed from a Linux box. PyInstaller
only targets the OS it runs on, so the bootstrap `.exe` cannot be built
locally on Linux — use the GitHub Actions workflow or a Windows machine.

## Bootstrap installer (`installer/bootstrap.py`)

A small PyInstaller `--onefile` exe that, on first run, downloads Python,
pip, Tesseract, and the fishbot source into `%LOCALAPPDATA%\Fishbot`,
then `pip install -e`s the source. Idempotent — each step has its own
existence check.

Three non-obvious constraints baked into this script:

1. **UB-Mannheim's Tesseract installer requires admin.** It's an Inno
   Setup package with `PrivilegesRequired=admin`, so plain
   `subprocess.run(setup_exe, ...)` fails with `WinError 740`
   (`ERROR_ELEVATION_REQUIRED`). The bootstrap launches it through
   `ShellExecuteExW` with the `runas` verb (`_run_elevated`) so Windows
   shows one UAC prompt. The bootstrapper itself stays per-user.

2. **Embeddable Python breaks pip's PEP 517 build isolation.** The
   embeddable distribution ships with a `python<ver>._pth` file that
   constrains `sys.path`, so when pip spawns a child Python to invoke a
   build backend in its temporary build env, the backend (e.g.
   `hatchling`) fails to import → `BackendUnavailable`. Fix: pre-install
   `hatchling`, `editables`, `setuptools`, and `wheel` into our Python,
   then run the editable install with `--no-build-isolation`. Don't try
   to "clean up" by re-enabling isolation — it will break again.

3. **`_run` must capture output.** Pip failures inside the bootstrap
   surface as a UAC-style modal dialog, so an unhelpful
   `CalledProcessError` is invisible. `_run` captures stdout+stderr and
   raises a `RuntimeError` with the last ~40 lines of each. Keep that
   behavior when editing.

The bootstrap also reuses an already-installed Tesseract if it finds one
on `PATH` or in standard `Program Files` / `LOCALAPPDATA\Programs`
locations (`_find_existing_tesseract`), avoiding a redundant UAC prompt.

## Releasing

`.github/workflows/release-installer.yml` builds and publishes the
`fishbot-setup.exe` on **tag push matching `v*`**.

```bash
git tag -a vX.Y.Z -m "vX.Y.Z - <summary>"
git push origin vX.Y.Z
```

The workflow injects `FISHBOT_SOURCE_URL` so the baked-in source URL
points at that tag's archive zip — release artifact and source are
self-consistent. Manual `workflow_dispatch` runs upload the exe as a
workflow artifact instead of attaching it to a release.

If you need a manual run from a branch:

```bash
gh workflow run release-installer.yml --ref <branch>
gh run list --workflow release-installer.yml --limit 1
gh run download <run-id> -n fishbot-setup
```

## Layout

- `src/fishbot/` — runtime package (`gui.py`, `main.py`, `vision.py`, …).
- `installer/bootstrap.py` — the one-shot bootstrapper described above.
- `installer/bootstrap.spec` — PyInstaller spec, built via
  `installer/build-bootstrap.ps1` from a repo-isolated venv so the exe
  stays small.
- `installer/fishbot.iss`, `installer/fishbot.spec`,
  `installer/fishbot-gui.spec` — older full-Inno-Setup installer path,
  not used by the bootstrap workflow.
- Build backend is **hatchling** (`pyproject.toml`); the wheel package is
  `src/fishbot`.
