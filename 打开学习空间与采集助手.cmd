@echo off
cd /d "%~dp0"
python launch_collector.py
if errorlevel 1 pause
