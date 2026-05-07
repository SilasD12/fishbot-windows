@echo off
rem Dev-mode launcher for the bot CLI. The installed app uses fishbot.exe
rem directly; this script is for running from a checkout.
setlocal
cd /d "%~dp0\.."
python -m fishbot.main %*
