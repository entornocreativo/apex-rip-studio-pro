@echo off
title ApexRIP - Capturador de Archivo .PRN Real (Mutoh / Mimaki)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0capture_prn_listener.ps1"
pause
