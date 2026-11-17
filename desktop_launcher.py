#!/usr/bin/env python3
"""
Lanzador directo de Escritorio para ApexRIP Studio Pro.
Ejecuta el servidor local FastAPI/Uvicorn del motor RIP en el puerto 8765.
"""

import os
import sys
import uvicorn

if __name__ == "__main__":
    backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
    sys.path.insert(0, backend_dir)
    print("=================================================================")
    print("  ApexRIP Studio Pro v2.4 — Motor RIP Gran Formato Iniciado")
    print("  Interfaz de Escritorio / Local: http://localhost:8765")
    print("=================================================================")
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=False)
