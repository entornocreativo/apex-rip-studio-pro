"""
Servidor Backend FastAPI del Software RIP de Escritorio (ApexRIP Studio Pro):
Específicamente configurado para:
1. Mutoh ValueJet VJ-1624 (Ecosolvente, hasta 1625mm de ancho, bobina máxima 50 metros)
2. Mimaki UJV100-160 (UV LED Curable CMYK + Blanco/Barniz, hasta 1620mm de ancho, bobina máxima 50 metros)
Permite escribir libremente el ancho de cada material, controlar el largo de bobina de hasta 50 metros (50,000 mm)
y crear/guardar perfiles personalizados para cada tipo de material.
"""

import base64
import io
import os
import time
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image

from color_engine import (
    BUILTIN_SPOT_LIBRARY,
    ICC_MEDIA_PROFILES,
    enrich_spot_color,
    generate_color_atlas,
)
from rip_engine import rip_image_pipeline, build_prn_binary_stream
from workflow_engine import compute_tiling_plan, compute_nesting_layout, render_vdp_batch_preview
from hardware_spooler import (
    PLOTTER_HARDWARE_MODELS,
    MAX_COIL_LENGTH_MM,
    detect_local_usb_and_cups_devices,
    send_prn_to_printer,
)
from sample_artwork import create_sample_wide_format_artwork

app = FastAPI(title="ApexRIP Studio Pro — Mutoh VJ-1624 & Mimaki UJV100-160", version="2.5.0")

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


STATE: Dict[str, Any] = {
    "spot_colors": [enrich_spot_color(item) for item in BUILTIN_SPOT_LIBRARY],
    "queues": [
        {
            "id": "queue_mutoh",
            "code": "COLA MUTOH",
            "name": "Mutoh ValueJet VJ-1624 (Ecosolvente)",
            "printer_id": "mutoh_vj_1624",
            "profile_id": "mutoh_vinyl_gloss_1370",
            "roll_width_mm": 1370.0,
            "coil_length_m": 50.0,
            "status": "En línea (i² Wave Activo)",
            "jobs": [
                {
                    "id": "JOB-101",
                    "title": "Grafica_Vehicular_Vinilo_137cm.tif",
                    "width_mm": 1320.0,
                    "height_mm": 2400.0,
                    "copies": 1,
                    "status": "Listo para Ripear",
                    "queue_id": "queue_mutoh",
                    "ink_ml": 14.20,
                    "color": "#0ea5e9",
                },
                {
                    "id": "JOB-102",
                    "title": "Stickers_Corporativos_Lote.pdf",
                    "width_mm": 620.0,
                    "height_mm": 900.0,
                    "copies": 2,
                    "status": "En Espera",
                    "queue_id": "queue_mutoh",
                    "ink_ml": 5.40,
                    "color": "#ec4899",
                },
            ],
        },
        {
            "id": "queue_mimaki",
            "code": "COLA MIMAKI",
            "name": "Mimaki UJV100-160 (UV LED + Blanco/Barniz)",
            "printer_id": "mimaki_ujv100_160",
            "profile_id": "mimaki_uv_vinyl_1520",
            "roll_width_mm": 1520.0,
            "coil_length_m": 50.0,
            "status": "En línea (MAPS4 / UV LED)",
            "jobs": [
                {
                    "id": "JOB-201",
                    "title": "Backlit_Film_UV_Blanco_150cm.tif",
                    "width_mm": 1480.0,
                    "height_mm": 1800.0,
                    "copies": 1,
                    "status": "Listo para Ripear",
                    "queue_id": "queue_mimaki",
                    "ink_ml": 12.80,
                    "color": "#10b981",
                }
            ],
        },
    ],
    "master_queue": [
        {
            "id": "MST-8801",
            "title": "Tirada_Lona_Frontlit_12m [RIPEADO]",
            "printer_model": "Mutoh ValueJet VJ-1624",
            "profile_name": "Mutoh VJ-1624 — Lona Frontlit 13oz (1600mm)",
            "resolution": "720x720 DPI (6 Pasadas Bidir)",
            "ink_ml": 68.40,
            "ripped_at": "Hoy",
            "prn_file": None,
        }
    ],
    "last_halftones": None,
}


class CreateMaterialProfileRequest(BaseModel):
    name: str
    printer_id: str = "mutoh_vj_1624"
    default_width_mm: float = 1370.0
    coil_length_m: float = 50.0
    total_ink_limit: int = 270
    black_generation: str = "GCR Medio"
    resolution: str = "720x1440"
    passes: int = 8
    gain_c: float = 1.0
    gain_m: float = 1.0
    gain_y: float = 1.0
    gain_k: float = 1.0
    gain_w: float = 0.0
    heater_pre_c: int = 40
    heater_platen_c: int = 42
    heater_dryer_c: int = 48
    uv_lamp_pct: int = 85


class RipRequest(BaseModel):
    preset_artwork: str = "motorsport_wrap"
    image_data_url: Optional[str] = None
    job_title: str = "Grafica_Gran_Formato.tif"
    queue_id: str = "queue_mutoh"
    printer_id: str = "mutoh_vj_1624"
    profile_id: str = "mutoh_vinyl_gloss_1370"
    halftone_mode: str = "bayer_fm"
    channel_gains: Dict[str, float] = {"C": 1.0, "M": 1.0, "Y": 1.0, "K": 1.0}
    total_ink_limit: float = 270.0
    mirror_horizontal: bool = False
    material_width_mm: float = 1370.0
    coil_length_m: float = 50.0
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
    profile_id: str = "mutoh_vinyl_gloss_1370"
    include_crop_marks: bool = True


class SpotColorImportRequest(BaseModel):
    code: str
    name: str
    L: float
    a: float
    b: float
    category: str = "Custom CIE Lab / PANTONE"
    profile_id: str = "mutoh_vinyl_gloss_1370"


class TilingRequest(BaseModel):
    job_width_mm: float = 4200.0
    job_height_mm: float = 2400.0
    roll_width_mm: float = 1370.0
    margin_mm: float = 15.0
    overlap_mm: float = 18.0
    max_tile_height_mm: float = MAX_COIL_LENGTH_MM
    alternate_flip: bool = True


class NestingRequest(BaseModel):
    queue_id: str = "queue_mutoh"
    roll_width_mm: float = 1370.0
    margin_mm: float = 15.0
    gap_mm: float = 12.0
    allow_rotation: bool = True
    custom_items: Optional[List[Dict[str, Any]]] = None


class VdpRequest(BaseModel):
    records: List[Dict[str, str]]
    queue_id: str = "queue_mutoh"


class SpoolSendRequest(BaseModel):
    job_title: str = "Trabajo_RIP_GranFormato"
    printer_id: str = "mutoh_vj_1624"
    profile_id: str = "mutoh_vinyl_gloss_1370"
    connection_mode: str = "spool_file"
    host: str = "192.168.1.201"
    port: int = 9100
    usb_device: str = "/dev/usb/lp0"
    resolution_dpi: int = 720
    passes: int = 8
    head_direction: str = "bidirectional"
    auto_cut: bool = True
    roll_width_mm: float = 1370.0


@app.get("/api/config")
def get_initial_config() -> Dict[str, Any]:
    return {
        "max_coil_length_m": 50.0,
        "max_coil_length_mm": MAX_COIL_LENGTH_MM,
        "printers": list(PLOTTER_HARDWARE_MODELS.values()),
        "profiles": list(ICC_MEDIA_PROFILES.values()),
        "spot_colors": STATE["spot_colors"],
        "queues": STATE["queues"],
        "master_queue": STATE["master_queue"],
        "devices": detect_local_usb_and_cups_devices(),
    }


@app.post("/api/profiles/create")
def api_create_material_profile(req: CreateMaterialProfileRequest) -> Dict[str, Any]:
    prof_id = f"custom_{int(time.time())}"
    is_uv = req.printer_id == "mimaki_ujv100_160"
    new_prof = {
        "id": prof_id,
        "name": req.name.strip(),
        "printer_id": req.printer_id,
        "ink_type": "UV LED CMYK + Blanco" if is_uv else "Ecosolvente CMYK (Mutoh i²)",
        "default_width_mm": max(210.0, min(1625.0, req.default_width_mm)),
        "coil_length_m": max(1.0, min(50.0, req.coil_length_m)),
        "rendering_intent": "Perceptual",
        "total_ink_limit": req.total_ink_limit,
        "black_generation": req.black_generation,
        "channel_gains": {
            "C": req.gain_c,
            "M": req.gain_m,
            "Y": req.gain_y,
            "K": req.gain_k,
            "W": req.gain_w,
        },
        "heaters_c": {
            "pre": 0 if is_uv else req.heater_pre_c,
            "platen": 0 if is_uv else req.heater_platen_c,
            "dryer": 0 if is_uv else req.heater_dryer_c,
        },
        "uv_lamp_pct": req.uv_lamp_pct if is_uv else 0,
        "resolution": req.resolution,
        "passes": req.passes,
        "gamma": 1.0,
    }
    ICC_MEDIA_PROFILES[prof_id] = new_prof
    return {
        "created": new_prof,
        "profiles": list(ICC_MEDIA_PROFILES.values()),
    }


@app.post("/api/rip/process")
def api_rip_process(req: RipRequest) -> Dict[str, Any]:
    if req.image_data_url:
        img = data_url_to_pil(req.image_data_url)
    else:
        img = create_sample_wide_format_artwork(preset=req.preset_artwork)

    clamped_h_mm = min(MAX_COIL_LENGTH_MM, max(10.0, req.height_mm))
    result = rip_image_pipeline(
        img=img,
        profile_id=req.profile_id,
        halftone_mode=req.halftone_mode,
        channel_gains=req.channel_gains,
        total_ink_limit=req.total_ink_limit,
        mirror_horizontal=req.mirror_horizontal,
        width_mm=req.width_mm,
        height_mm=clamped_h_mm,
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
        "metrics": {
            **result["metrics"],
            "material_width_mm": req.material_width_mm,
            "coil_length_m": min(50.0, req.coil_length_m),
            "remaining_coil_m": round(max(0.0, min(50.0, req.coil_length_m) - (clamped_h_mm / 1000.0)), 2),
        },
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
        job_height_mm=min(MAX_COIL_LENGTH_MM, req.job_height_mm),
        roll_width_mm=req.roll_width_mm,
        margin_mm=req.margin_mm,
        overlap_mm=req.overlap_mm,
        max_tile_height_mm=min(MAX_COIL_LENGTH_MM, req.max_tile_height_mm),
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
    printer_obj = PLOTTER_HARDWARE_MODELS.get(req.printer_id, PLOTTER_HARDWARE_MODELS["mutoh_vj_1624"])
    prof_obj = ICC_MEDIA_PROFILES.get(req.profile_id, ICC_MEDIA_PROFILES["mutoh_vinyl_gloss_1370"])

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
