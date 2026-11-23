@echo off
cd /d "%~dp0"
python launch_collector.py --browser chrome
if errorlevel 1 pause
