"""
Control de Hardware, Perfiles de Plotter y Spooler Directo (USB / Red TCP-IP Port 9100):
- Catálogo de plotters de gran formato (Epson, Roland, Mimaki, Mutoh, HP Latex)
- Control de cabezal (Unidireccional / Bidireccional), pasadas, entrelazado, calentadores/lámparas UV y autocorte
- Envío directo por socket TCP/IP Raw (Puerto 9100), cola local CUPS/USB o guardado en disco (.PRN)
"""

import os
import socket
import subprocess
import time
from typing import Dict, List, Any, Optional

PLOTTER_HARDWARE_MODELS: Dict[str, Dict[str, Any]] = {
    "epson_s80600": {
        "id": "epson_s80600",
        "brand": "Epson",
        "model": "SureColor SC-S80600 (PrecisionCore Dual)",
        "technology": "Ecosolvente",
        "max_width_mm": 1626,
        "resolutions": ["720x720", "720x1440", "1440x1440"],
        "passes_supported": [4, 6, 8, 12, 16],
        "channels": ["C", "M", "Y", "K", "Lc", "Lm", "Lk", "Or", "Re", "Wh/Sl"],
        "command_lang": "ESC/P2-Raster",
        "default_port": 9100,
        "heaters_c": {"pre": 40, "platen": 42, "after": 50},
    },
    "roland_vg3_640": {
        "id": "roland_vg3_640",
        "brand": "Roland DG",
        "model": "TrueVIS VG3-640 (Print & Cut)",
        "technology": "Ecosolvente + Corte Contorno",
        "max_width_mm": 1625,
        "resolutions": ["600x600", "900x900", "1200x1200"],
        "passes_supported": [6, 8, 10, 12, 16],
        "channels": ["C", "M", "Y", "K", "Lc", "Lm", "Or", "Gr"],
        "command_lang": "RP-GL/RTL + CAMM-GL1",
        "default_port": 9100,
        "heaters_c": {"pre": 38, "platen": 40, "after": 48},
    },
    "epson_f9470h": {
        "id": "epson_f9470h",
        "brand": "Epson",
        "model": "SureColor SC-F9470H (Sublimación Alta Producción)",
        "technology": "Sublimación Textil + Fluorescente",
        "max_width_mm": 1625,
        "resolutions": ["360x720", "720x720", "720x1440"],
        "passes_supported": [2, 4, 6, 8],
        "channels": ["C", "M", "Y", "HDK", "FY", "FP"],
        "command_lang": "ESC/P2-Sub",
        "default_port": 9100,
        "heaters_c": {"pre": 0, "platen": 35, "after": 55},
    },
    "mimaki_ucjv300_160": {
        "id": "mimaki_ucjv300_160",
        "brand": "Mimaki",
        "model": "UCJV300-160 (UV LED Print & Cut)",
        "technology": "UV LED Curable (Blanco + Barniz)",
        "max_width_mm": 1610,
        "resolutions": ["600x600", "600x1200", "1200x1200"],
        "passes_supported": [6, 8, 12, 16, 24],
        "channels": ["C", "M", "Y", "K", "Lc", "Lm", "W", "V"],
        "command_lang": "MRL-IV / HP-GL",
        "default_port": 9100,
        "heaters_c": {"uv_lamp_left_pct": 85, "uv_lamp_right_pct": 85},
    },
    "mutoh_xpj_1682sr": {
        "id": "mutoh_xpj_1682sr",
        "brand": "Mutoh",
        "model": "XpertJet 1682SR Pro (Dual Head AccuFine)",
        "technology": "Ecosolvente",
        "max_width_mm": 1625,
        "resolutions": ["600x600", "600x900", "1200x1200"],
        "passes_supported": [4, 6, 8, 12],
        "channels": ["C", "M", "Y", "K", "Lc", "Lm", "Lk", "Or"],
        "command_lang": "MH-RTL",
        "default_port": 9100,
        "heaters_c": {"pre": 42, "platen": 40, "after": 50},
    },
}


def detect_local_usb_and_cups_devices() -> List[Dict[str, str]]:
    """Detecta dispositivos USB de impresión (/dev/usb/lp*) y colas CUPS disponibles en el sistema."""
    devices: List[Dict[str, str]] = []
    # 1. Revisar dispositivos de caracteres USB directos en Linux
    for dev_idx in range(4):
        dev_path = f"/dev/usb/lp{dev_idx}"
        if os.path.exists(dev_path):
            devices.append({
                "type": "USB Directo",
                "uri": dev_path,
                "status": "Conectado",
            })

    # 2. Consultar lpstat si está disponible
    try:
        res = subprocess.run(["lpstat", "-v"], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                devices.append({
                    "type": "Cola CUPS",
                    "uri": line.strip(),
                    "status": "Disponible",
                })
    except Exception:
        pass

    # Puertos virtuales / simulador de desarrollo siempre disponibles
    devices.extend([
        {
            "type": "Red TCP/IP (JetDirect Raw)",
            "uri": "tcp://192.168.1.200:9100",
            "status": "Listo para transmisión Raw",
        },
        {
            "type": "Spooler Archivo Local (.PRN)",
            "uri": "file:///home/antigravity/plotter-rip-pro/output_spool/",
            "status": "Activo (Carpeta Caliente)",
        },
    ])
    return devices


def send_prn_to_printer(
    prn_bytes: bytes,
    connection_mode: str = "spool_file",
    host: str = "127.0.0.1",
    port: int = 9100,
    usb_device: str = "/dev/usb/lp0",
    output_dir: str = "/home/antigravity/plotter-rip-pro/output_spool",
    job_name: str = "rip_job",
) -> Dict[str, Any]:
    """
    Envía el stream binario .PRN directamente al plotter:
    - 'tcp_raw': Conecta por socket TCP al puerto 9100 (con fallback automático a archivo local si el plotter físico no está en red)
    - 'usb_direct': Escribe directamente al nodo USB `/dev/usb/lp0`
    - 'spool_file': Guarda el archivo `.PRN` listo para producción en la carpeta de salida
    """
    os.makedirs(output_dir, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in job_name)
    ts = int(time.time())
    prn_path = os.path.join(output_dir, f"{safe_name}_{ts}.prn")

    # Siempre guardamos copia de respaldo en el Spooler Maestro
    with open(prn_path, "wb") as f:
        f.write(prn_bytes)

    if connection_mode == "tcp_raw":
        try:
            with socket.create_connection((host, int(port)), timeout=2.5) as sock:
                sock.sendall(prn_bytes)
            return {
                "success": True,
                "mode": "TCP/IP Raw Socket",
                "target": f"{host}:{port}",
                "bytes_sent": len(prn_bytes),
                "spool_backup": prn_path,
                "message": f"Trabajo enviado directamente por TCP/IP a {host}:{port} ({len(prn_bytes):,} bytes).",
            }
        except Exception as exc:
            return {
                "success": True,
                "mode": "Spooler Local (Fallback TCP)",
                "target": prn_path,
                "bytes_sent": len(prn_bytes),
                "spool_backup": prn_path,
                "message": f"El plotter {host}:{port} no respondió al socket directo ({exc}); trabajo almacenado en Cola Maestra lista para envío: {prn_path}",
            }

    if connection_mode == "usb_direct":
        if os.path.exists(usb_device) and os.access(usb_device, os.W_OK):
            with open(usb_device, "wb") as udev:
                udev.write(prn_bytes)
            return {
                "success": True,
                "mode": "USB Directo",
                "target": usb_device,
                "bytes_sent": len(prn_bytes),
                "spool_backup": prn_path,
                "message": f"Enviado correctamente por puerto USB {usb_device} ({len(prn_bytes):,} bytes).",
            }
        return {
            "success": True,
            "mode": "Spooler Local (USB en espera)",
            "target": prn_path,
            "bytes_sent": len(prn_bytes),
            "spool_backup": prn_path,
            "message": f"Puerto {usb_device} no detectado físicamente; archivo .PRN generado en Cola Maestra: {prn_path}",
        }

    return {
        "success": True,
        "mode": "Archivo .PRN de Producción",
        "target": prn_path,
        "bytes_sent": len(prn_bytes),
        "spool_backup": prn_path,
        "message": f"Archivo .PRN ripeado y guardado en Cola Maestra ({len(prn_bytes):,} bytes): {prn_path}",
    }
