@echo off
title ApexRIP Studio Pro v2.4 - Lanzador para Windows
echo =================================================================
echo   ApexRIP Studio Pro v2.4 - Software RIP de Gran Formato
echo =================================================================
echo.
echo [1/2] Verificando si Python esta instalado en este equipo...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo No se detecto Python en el PATH. Abriendo version Portable HTML directa...
    start "" "%~dp0ApexRIP_Studio_Pro_Portable.html"
    exit /b 0
)

echo [2/2] Instalando dependencias ligeras (Pillow, NumPy, FastAPI, Uvicorn)...
python -m pip install --quiet pillow numpy fastapi uvicorn
echo Iniciando motor Python RIP en http://127.0.0.1:8765 ...
start "" "http://127.0.0.1:8765"
python "%~dp0desktop_launcher.py"
pause
