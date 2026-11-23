@echo off
cd /d "%~dp0"
python launch_collector.py --portal-only
if errorlevel 1 pause
