@echo off
title ApexRIP Studio Pro - Motor RIP + Conexion Red TCP/IP 9100
cd /d "%~dp0"

echo ============================================================================
echo   APEXRIP STUDIO PRO - INICIANDO SERVIDOR DE IMPRESION EN RED (PUERTO 9100)
echo ============================================================================

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Python detectado. Iniciando motor RIP FastAPI en http://127.0.0.1:8765 ...
    python desktop_launcher.py
) else (
    echo [INFO] Iniciando Puente Nativo de Impresion Windows TCP/IP Puerto 9100 ...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows_network_bridge.ps1"
)
pause
