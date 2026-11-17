@echo off
title ApexRIP SoftRIP Edition - Conector Directo de Impresoras en Red (TCP/IP Puerto 9100)
cd /d "%~dp0"

echo ============================================================================
echo   APEXRIP SOFTRIP v3.3 - CONECTOR DE IMPRESORAS EN RED (MUTOH / MIMAKI)
echo   Activa la impresion directa por Red LAN (TCP/IP Puerto 9100) y Cola Windows
echo ============================================================================
echo.

REM Ejecutar el puente nativo de Windows (.NET HttpListener + TcpClient Puerto 9100)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows_network_bridge.ps1"
pause
