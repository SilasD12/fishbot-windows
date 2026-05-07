@echo off
rem Dev-mode launcher for the GUI. Uses pythonw so no console window appears.
setlocal
cd /d "%~dp0\.."
start "" pythonw -m fishbot.gui
