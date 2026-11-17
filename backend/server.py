"""
Servidor Backend FastAPI del Software RIP de Escritorio (ApexRIP Studio Pro):
Conecta la interfaz de escritorio (Electron / Web UI) con el motor Python de Ripeo,
Gestión de Color ICC/Lab/PANTONE, Atlas de Color, Colas Múltiples, Panelación, VDP y Spooler TCP/USB.
"""

import base64
import io
import os
import time
import uuid
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image

from color_engine import (
    BUILTIN_SPOT_LIBRARY,
    ICC_MEDIA_PROFILES,
    enrich_spot_color,
    generate_color_atlas,
    srgb_to_lab,
    rgb_to_device_cmyk,
)
from rip_engine import rip_image_pipeline, build_prn_binary_stream
from workflow_engine import compute_tiling_plan, compute_nesting_layout, render_vdp_batch_preview
from hardware_spooler import (
    PLOTTER_HARDWARE_MODELS,
    detect_local_usb_and_cups_devices,
    send_prn_to_printer,
)
from sample_artwork import create_sample_wide_format_artwork

app = FastAPI(title="ApexRIP Studio Pro — Wide Format RIP Engine", version="2.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPOOL_DIR = os.path.join(BASE_DIR, "output_spool")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
os.makedirs(SPOOL_DIR, exist_ok=True)


def pil_to_data_url(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/png" if fmt.upper() == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def data_url_to_pil(data_url: str) -> Image.Image:
    if "," in data_url:
        _, b64 = data_url.split(",", 1)
    else:
        b64 = data_url
    raw = base64.b64decode(b64)
    return Image.open(io.BytesIO(raw))


# Estado en memoria de Colas de Impresión Múltiples, Cola Maestra y Biblioteca PANTONE/Lab
STATE: Dict[str, Any] = {
    "spot_colors": [enrich_spot_color(item) for item in BUILTIN_SPOT_LIBRARY],
    "queues": [
        {
            "id": "queue_a",
            "code": "COLA A",
            "name": "Ecosolvente — Vinilo & Lona 160cm",
            "printer_id": "epson_s80600",
            "profile_id": "ecosol_vinyl_gloss",
            "roll_width_mm": 1600.0,
            "status": "Lista / En línea",
            "jobs": [
                {
                    "id": "JOB-101",
                    "title": "Gráfica Vehicular Racing Team.tif",
                    "width_mm": 1450.0,
                    "height_mm": 950.0,
                    "copies": 1,
                    "status": "Listo para Ripear",
                    "queue_id": "queue_a",
                    "ink_ml": 5.84,
                    "color": "#0ea5e9",
                },
                {
                    "id": "JOB-102",
                    "title": "Stickers Corporativos Troquelados.pdf",
                    "width_mm": 480.0,
                    "height_mm": 350.0,
                    "copies": 3,
                    "status": "En Espera",
                    "queue_id": "queue_a",
                    "ink_ml": 2.15,
                    "color": "#ec4899",
                },
            ],
        },
        {
            "id": "queue_b",
            "code": "COLA B",
            "name": "Sublimación Textil — Transfer 110cm",
            "printer_id": "epson_f9470h",
            "profile_id": "sublimation_transfer_paper",
            "roll_width_mm": 1118.0,
            "status": "Activa (Espejado Auto)",
            "jobs": [
                {
                    "id": "JOB-201",
                    "title": "Camisetas Deportivas Full Print.eps",
                    "width_mm": 980.0,
                    "height_mm": 1200.0,
                    "copies": 2,
                    "status": "Listo para Ripear",
                    "queue_id": "queue_b",
                    "ink_ml": 7.10,
                    "color": "#eab308",
                }
            ],
        },
        {
            "id": "queue_c",
            "code": "COLA C",
            "name": "UV LED Print & Cut — Blanco + Barniz",
            "printer_id": "mimaki_ucjv300_160",
            "profile_id": "uv_rigid_acrylic",
            "roll_width_mm": 1600.0,
            "status": "En espera de lote",
            "jobs": [
                {
                    "id": "JOB-301",
                    "title": "Etiquetas Domo Relieve UV + Blanco.pdf",
                    "width_mm": 600.0,
                    "height_mm": 400.0,
                    "copies": 2,
                    "status": "Listo para Ripear",
                    "queue_id": "queue_c",
                    "ink_ml": 4.30,
                    "color": "#10b981",
                }
            ],
        },
    ],
    "master_queue": [
        {
            "id": "MST-8801",
            "title": "Campaña Vial Exterior 150x100cm [RIPEADO]",
            "printer_model": "Epson SureColor SC-S80600",
            "profile_name": "Vinilo Adhesivo Brillante (Ecosolvente)",
            "resolution": "720x1440 DPI (8 Pasadas Bidir)",
            "ink_ml": 6.42,
            "ripped_at": "Hoy, 05:50",
            "prn_file": None,
        }
    ],
    "last_halftones": None,
}


class RipRequest(BaseModel):
    preset_artwork: str = "motorsport_wrap"
    image_data_url: Optional[str] = None
    job_title: str = "Gráfica Gran Formato.tif"
    queue_id: str = "queue_a"
    printer_id: str = "epson_s80600"
    profile_id: str = "ecosol_vinyl_gloss"
    halftone_mode: str = "bayer_fm"
    channel_gains: Dict[str, float] = {"C": 1.0, "M": 1.0, "Y": 1.0, "K": 1.0}
    total_ink_limit: float = 280.0
    mirror_horizontal: bool = False
    width_mm: float = 1200.0
    height_mm: float = 840.0
    resolution_dpi: int = 720
    passes: int = 8
    head_direction: str = "bidirectional"
    auto_cut: bool = True
    add_crop_marks: bool = True
    add_printline: bool = True
    add_colorbar: bool = True
    generate_white_underbase: bool = False


class AtlasRequest(BaseModel):
    base_hex: str = "#E1251B"
    rows: int = 5
    cols: int = 5
    step_pct: float = 4.0
    variation_mode: str = "C_vs_M"
    profile_id: str = "ecosol_vinyl_gloss"
    include_crop_marks: bool = True


class SpotColorImportRequest(BaseModel):
    code: str
    name: str
    L: float
    a: float
    b: float
    category: str = "Custom CIE Lab / PANTONE"
    profile_id: str = "ecosol_vinyl_gloss"


class TilingRequest(BaseModel):
    job_width_mm: float = 3800.0
    job_height_mm: float = 2200.0
    roll_width_mm: float = 1600.0
    margin_mm: float = 20.0
    overlap_mm: float = 15.0
    max_tile_height_mm: float = 3000.0
    alternate_flip: bool = True


class NestingRequest(BaseModel):
    queue_id: str = "queue_a"
    roll_width_mm: float = 1600.0
    margin_mm: float = 15.0
    gap_mm: float = 12.0
    allow_rotation: bool = True
    custom_items: Optional[List[Dict[str, Any]]] = None


class VdpRequest(BaseModel):
    records: List[Dict[str, str]]
    queue_id: str = "queue_a"


class SpoolSendRequest(BaseModel):
    job_title: str = "Trabajo_RIP_GranFormato"
    printer_id: str = "epson_s80600"
    profile_id: str = "ecosol_vinyl_gloss"
    connection_mode: str = "spool_file"
    host: str = "192.168.1.200"
    port: int = 9100
    usb_device: str = "/dev/usb/lp0"
    resolution_dpi: int = 720
    passes: int = 8
    head_direction: str = "bidirectional"
    auto_cut: bool = True
    roll_width_mm: float = 1600.0


@app.get("/api/config")
def get_initial_config() -> Dict[str, Any]:
    return {
        "printers": list(PLOTTER_HARDWARE_MODELS.values()),
        "profiles": list(ICC_MEDIA_PROFILES.values()),
        "spot_colors": STATE["spot_colors"],
        "queues": STATE["queues"],
        "master_queue": STATE["master_queue"],
        "devices": detect_local_usb_and_cups_devices(),
    }


@app.post("/api/rip/process")
def api_rip_process(req: RipRequest) -> Dict[str, Any]:
    if req.image_data_url:
        img = data_url_to_pil(req.image_data_url)
    else:
        img = create_sample_wide_format_artwork(preset=req.preset_artwork)

    result = rip_image_pipeline(
        img=img,
        profile_id=req.profile_id,
        halftone_mode=req.halftone_mode,
        channel_gains=req.channel_gains,
        total_ink_limit=req.total_ink_limit,
        mirror_horizontal=req.mirror_horizontal,
        width_mm=req.width_mm,
        height_mm=req.height_mm,
        resolution_dpi=req.resolution_dpi,
        passes=req.passes,
        head_direction=req.head_direction,
        auto_cut=req.auto_cut,
        add_crop_marks=req.add_crop_marks,
        add_printline=req.add_printline,
        add_colorbar=req.add_colorbar,
        generate_white_underbase=req.generate_white_underbase,
    )

    STATE["last_halftones"] = result["raw_halftones"]

    return {
        "job_title": req.job_title,
        "previews": {
            "composite": pil_to_data_url(result["composite_image"]),
            "C": pil_to_data_url(result["channels"]["C"]),
            "M": pil_to_data_url(result["channels"]["M"]),
            "Y": pil_to_data_url(result["channels"]["Y"]),
            "K": pil_to_data_url(result["channels"]["K"]),
        },
        "metrics": result["metrics"],
    }


@app.post("/api/color/atlas")
def api_generate_atlas(req: AtlasRequest) -> Dict[str, Any]:
    atlas = generate_color_atlas(
        base_hex=req.base_hex,
        rows=max(3, min(9, req.rows)),
        cols=max(3, min(9, req.cols)),
        step_pct=req.step_pct,
        variation_mode=req.variation_mode,
        profile_id=req.profile_id,
        include_crop_marks=req.include_crop_marks,
    )
    img_url = pil_to_data_url(atlas["image"])
    return {
        "base_hex": atlas["base_hex"],
        "base_cmyk": atlas["base_cmyk"],
        "rows": atlas["rows"],
        "cols": atlas["cols"],
        "step_pct": atlas["step_pct"],
        "variation_mode": atlas["variation_mode"],
        "patches": atlas["patches"],
        "atlas_image_url": img_url,
    }


@app.post("/api/color/import-spot")
def api_import_spot_color(req: SpotColorImportRequest) -> Dict[str, Any]:
    new_entry = enrich_spot_color(
        {
            "code": req.code.strip(),
            "name": req.name.strip(),
            "L": req.L,
            "a": req.a,
            "b": req.b,
            "category": req.category,
        },
        profile_id=req.profile_id,
    )
    STATE["spot_colors"].insert(0, new_entry)
    return {
        "added": new_entry,
        "spot_colors": STATE["spot_colors"],
    }


@app.post("/api/workflow/tiling")
def api_compute_tiling(req: TilingRequest) -> Dict[str, Any]:
    return compute_tiling_plan(
        job_width_mm=req.job_width_mm,
        job_height_mm=req.job_height_mm,
        roll_width_mm=req.roll_width_mm,
        margin_mm=req.margin_mm,
        overlap_mm=req.overlap_mm,
        max_tile_height_mm=req.max_tile_height_mm,
        alternate_flip=req.alternate_flip,
    )


@app.post("/api/workflow/nesting")
def api_compute_nesting(req: NestingRequest) -> Dict[str, Any]:
    items = req.custom_items
    if not items:
        q = next((q for q in STATE["queues"] if q["id"] == req.queue_id), STATE["queues"][0])
        items = q["jobs"]
    return compute_nesting_layout(
        items=items,
        roll_width_mm=req.roll_width_mm,
        margin_mm=req.margin_mm,
        gap_mm=req.gap_mm,
        allow_rotation=req.allow_rotation,
    )


@app.post("/api/workflow/vdp")
def api_generate_vdp(req: VdpRequest) -> Dict[str, Any]:
    base_img = create_sample_wide_format_artwork("motorsport_wrap", width=240, height=240)
    vdp_res = render_vdp_batch_preview(base_img=base_img, records=req.records)
    # Añadir también como trabajo en la cola seleccionada
    q = next((q for q in STATE["queues"] if q["id"] == req.queue_id), STATE["queues"][0])
    new_job = {
        "id": f"VDP-{int(time.time()) % 10000}",
        "title": f"Lote Datos Variables ({vdp_res['total_records']} pzas).vdp",
        "width_mm": round(vdp_res["cols"] * 220.0, 1),
        "height_mm": round(vdp_res["rows"] * 130.0, 1),
        "copies": 1,
        "status": "Ripeado VDP Listo",
        "queue_id": q["id"],
        "ink_ml": round(vdp_res["total_records"] * 0.42, 2),
        "color": "#a855f7",
    }
    q["jobs"].insert(0, new_job)
    return {
        "total_records": vdp_res["total_records"],
        "sheet_image_url": pil_to_data_url(vdp_res["sheet_image"]),
        "queued_job": new_job,
        "queues": STATE["queues"],
    }


@app.post("/api/spool/send")
def api_spool_send(req: SpoolSendRequest) -> Dict[str, Any]:
    if STATE["last_halftones"] is None:
        img = create_sample_wide_format_artwork("motorsport_wrap")
        res = rip_image_pipeline(img=img, profile_id=req.profile_id)
        STATE["last_halftones"] = res["raw_halftones"]

    c_ht, m_ht, y_ht, k_ht = STATE["last_halftones"]
    printer_obj = PLOTTER_HARDWARE_MODELS.get(req.printer_id, PLOTTER_HARDWARE_MODELS["epson_s80600"])
    prof_obj = ICC_MEDIA_PROFILES.get(req.profile_id, ICC_MEDIA_PROFILES["ecosol_vinyl_gloss"])

    prn_bytes = build_prn_binary_stream(
        c_ht=c_ht,
        m_ht=m_ht,
        y_ht=y_ht,
        k_ht=k_ht,
        printer_model=printer_obj["model"],
        resolution_dpi=req.resolution_dpi,
        passes=req.passes,
        head_direction=req.head_direction,
        auto_cut=req.auto_cut,
        roll_width_mm=req.roll_width_mm,
    )

    spool_result = send_prn_to_printer(
        prn_bytes=prn_bytes,
        connection_mode=req.connection_mode,
        host=req.host,
        port=req.port,
        usb_device=req.usb_device,
        output_dir=SPOOL_DIR,
        job_name=req.job_title,
    )

    filename = os.path.basename(spool_result["spool_backup"])
    master_entry = {
        "id": f"MST-{int(time.time()) % 10000}",
        "title": f"{req.job_title} [RIPEADO]",
        "printer_model": printer_obj["model"],
        "profile_name": prof_obj["name"],
        "resolution": f"{req.resolution_dpi} DPI ({req.passes} Pasadas {'Unidir' if req.head_direction == 'unidirectional' else 'Bidir'})",
        "ink_ml": round(len(prn_bytes) / 14500.0, 2),
        "ripped_at": time.strftime("%H:%M:%S"),
        "prn_file": filename,
    }
    STATE["master_queue"].insert(0, master_entry)

    return {
        "spool": spool_result,
        "download_url": f"/api/spool/download/{filename}",
        "filename": filename,
        "master_queue": STATE["master_queue"],
    }


@app.get("/api/spool/download/{filename}")
def api_download_prn(filename: str):
    safe_name = os.path.basename(filename)
    full_path = os.path.join(SPOOL_DIR, safe_name)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Archivo .PRN no encontrado")
    return FileResponse(full_path, media_type="application/octet-stream", filename=safe_name)


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
