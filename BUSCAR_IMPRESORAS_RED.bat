@echo off
title ApexRIP - Busqueda Rapida de Impresoras en Red (Mutoh & Mimaki)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scan_printers_lan.ps1"
echo.
pause
