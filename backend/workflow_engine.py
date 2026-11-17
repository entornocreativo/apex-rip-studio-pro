"""
Motor de Flujo de Trabajo y Automatización RIP:
- Colas de Impresión Múltiples y Cola Maestra (trabajos ripeados listos para reimpresión)
- Composición / Nesting automático en rollo (optimización de aprovechamiento de sustrato)
- Panelación (Tiling) de imágenes de gran formato con solapamiento (overlap) y volteo alterno de paneles
- Impresión de Datos Variables (VDP) para producción seriada y personalizada
"""

import math
import time
import uuid
from typing import Dict, List, Any, Optional
from PIL import Image, ImageDraw, ImageOps


def compute_tiling_plan(
    job_width_mm: float,
    job_height_mm: float,
    roll_width_mm: float = 1600.0,
    margin_mm: float = 20.0,
    overlap_mm: float = 15.0,
    max_tile_height_mm: float = 3000.0,
    alternate_flip: bool = True,
) -> Dict[str, Any]:
    """
    Calcula la división (Panelación / Tiling) de una imagen de gran formato que excede
    el ancho útil del rollo (o largo máximo), generando las coordenadas de cada panel,
    áreas de solapamiento (overlap) y orientación alterna de cabezal.
    """
    usable_roll_w = max(100.0, roll_width_mm - 2.0 * margin_mm)
    overlap = max(0.0, min(overlap_mm, usable_roll_w * 0.25))

    if job_width_mm <= usable_roll_w:
        cols = 1
        step_w = job_width_mm
    else:
        effective_step = usable_roll_w - overlap
        cols = int(math.ceil((job_width_mm - overlap) / effective_step))
        step_w = (job_width_mm - overlap) / cols

    if job_height_mm <= max_tile_height_mm:
        rows = 1
        step_h = job_height_mm
    else:
        effective_h_step = max_tile_height_mm - overlap
        rows = int(math.ceil((job_height_mm - overlap) / effective_h_step))
        step_h = (job_height_mm - overlap) / rows

    tiles: List[Dict[str, Any]] = []
    total_linear_mm = 0.0

    for r in range(rows):
        for c in range(cols):
            x0 = round(c * step_w, 1)
            y0 = round(r * step_h, 1)
            w_tile = round(min(job_width_mm - x0, step_w + (overlap if c < cols - 1 else 0.0)), 1)
            h_tile = round(min(job_height_mm - y0, step_h + (overlap if r < rows - 1 else 0.0)), 1)
            flipped = bool(alternate_flip and (c % 2 == 1))
            tile_num = r * cols + c + 1
            tiles.append({
                "tile_id": f"P{tile_num:02d}",
                "row": r + 1,
                "col": c + 1,
                "x_mm": x0,
                "y_mm": y0,
                "width_mm": w_tile,
                "height_mm": h_tile,
                "overlap_right_mm": overlap if c < cols - 1 else 0.0,
                "overlap_bottom_mm": overlap if r < rows - 1 else 0.0,
                "flipped_180": flipped,
            })
            total_linear_mm += h_tile + 25.0  # +25mm separación entre paneles

    return {
        "job_width_mm": job_width_mm,
        "job_height_mm": job_height_mm,
        "roll_width_mm": roll_width_mm,
        "usable_roll_width_mm": usable_roll_w,
        "overlap_mm": overlap,
        "cols": cols,
        "rows": rows,
        "total_tiles": len(tiles),
        "estimated_roll_length_m": round(total_linear_mm / 1000.0, 2),
        "tiles": tiles,
    }


def compute_nesting_layout(
    items: List[Dict[str, Any]],
    roll_width_mm: float = 1600.0,
    margin_mm: float = 15.0,
    gap_mm: float = 10.0,
    allow_rotation: bool = True,
) -> Dict[str, Any]:
    """
    Motor de Composición y Nesting Automático (Shelf First-Fit Decreasing):
    Acomoda múltiples trabajos (y sus copias) dentro del ancho del rollo para
    minimizar el consumo lineal de material.
    """
    usable_w = max(100.0, roll_width_mm - 2.0 * margin_mm)
    expanded: List[Dict[str, Any]] = []

    for it in items:
        copies = max(1, int(it.get("copies", 1)))
        w = float(it.get("width_mm", 400.0))
        h = float(it.get("height_mm", 300.0))
        # Si rotar 90° mejora el encaje o permite entrar en el rollo
        rotated = False
        if allow_rotation and ((w > usable_w and h <= usable_w) or (h > w and h <= usable_w * 0.45)):
            w, h = h, w
            rotated = True
        w = min(w, usable_w)

        for cp in range(copies):
            expanded.append({
                "job_id": it.get("id", "JOB"),
                "title": it.get("title", "Trabajo"),
                "copy_index": cp + 1,
                "width_mm": round(w, 1),
                "height_mm": round(h, 1),
                "rotated_90": rotated,
                "color": it.get("color", "#0ea5e9"),
            })

    # Ordenar de mayor a menor altura para empaquetado óptimo por franjas
    expanded.sort(key=lambda x: (-x["height_mm"], -x["width_mm"]))

    shelves: List[Dict[str, Any]] = []
    placed: List[Dict[str, Any]] = []

    for piece in expanded:
        pw, ph = piece["width_mm"], piece["height_mm"]
        best_shelf = None
        for sh in shelves:
            if sh["remaining_w"] >= pw:
                best_shelf = sh
                break

        if best_shelf is None:
            y_start = margin_mm if not shelves else (shelves[-1]["y_mm"] + shelves[-1]["height_mm"] + gap_mm)
            best_shelf = {
                "y_mm": round(y_start, 1),
                "height_mm": ph,
                "x_cursor": margin_mm,
                "remaining_w": usable_w,
            }
            shelves.append(best_shelf)

        px = best_shelf["x_cursor"]
        py = best_shelf["y_mm"]
        best_shelf["x_cursor"] = round(px + pw + gap_mm, 1)
        best_shelf["remaining_w"] = round( (margin_mm + usable_w) - best_shelf["x_cursor"], 1)

        placed.append({
            **piece,
            "x_mm": round(px, 1),
            "y_mm": round(py, 1),
        })

    total_length_mm = margin_mm * 2.0
    if shelves:
        last = shelves[-1]
        total_length_mm = round(last["y_mm"] + last["height_mm"] + margin_mm, 1)

    used_area_mm2 = sum(p["width_mm"] * p["height_mm"] for p in placed)
    roll_area_mm2 = max(1.0, roll_width_mm * total_length_mm)
    efficiency_pct = round(min(100.0, (used_area_mm2 / roll_area_mm2) * 100.0), 1)

    return {
        "roll_width_mm": roll_width_mm,
        "usable_width_mm": usable_w,
        "total_length_mm": total_length_mm,
        "total_length_m": round(total_length_mm / 1000.0, 2),
        "total_pieces": len(placed),
        "efficiency_pct": efficiency_pct,
        "waste_pct": round(100.0 - efficiency_pct, 1),
        "placed_items": placed,
    }


def render_vdp_batch_preview(
    base_img: Optional[Image.Image],
    records: List[Dict[str, str]],
    badge_width_px: int = 340,
    badge_height_px: int = 190,
) -> Dict[str, Any]:
    """
    Motor de Impresión de Datos Variables (VDP):
    Genera una hoja impuesta con múltiples registros personalizados (Nombre, Código/Serie,
    Lote/QR simulado y marca de corte individual) listos para ripear e imprimir en serie.
    """
    if not records:
        records = [
            {"id": "SER-0001", "label": "OPERADOR PLANTA A", "sub": "LOTE 2026-X1"},
            {"id": "SER-0002", "label": "OPERADOR PLANTA B", "sub": "LOTE 2026-X1"},
            {"id": "SER-0003", "label": "SUPERVISOR CALIDAD", "sub": "LOTE 2026-X2"},
            {"id": "SER-0004", "label": "LOGÍSTICA CENTRAL", "sub": "LOTE 2026-X2"},
        ]

    cols = min(3, max(1, len(records)))
    rows = int(math.ceil(len(records) / cols))
    pad = 20
    sheet_w = pad + cols * (badge_width_px + pad)
    sheet_h = 56 + rows * (badge_height_px + pad)

    sheet = Image.new("RGB", (sheet_w, sheet_h), (248, 250, 252))
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 18), f"HOJA DE PRODUCCION VDP (DATOS VARIABLES) - {len(records)} REGISTROS SERIADOS", fill=(15, 23, 42))

    for idx, rec in enumerate(records):
        r = idx // cols
        c = idx % cols
        x0 = pad + c * (badge_width_px + pad)
        y0 = 52 + r * (badge_height_px + pad)
        x1 = x0 + badge_width_px
        y1 = y0 + badge_height_px

        # Fondo de etiqueta/pieza y línea de corte Printline magenta
        draw.rectangle([x0, y0, x1, y1], fill=(255, 255, 255), outline=(236, 0, 140), width=2)
        draw.rectangle([x0 + 6, y0 + 6, x1 - 6, y0 + 44], fill=(15, 23, 42))

        code_str = str(rec.get("id", f"SER-{idx+1:04d}"))
        label_str = str(rec.get("label", f"PIEZA #{idx+1}"))
        sub_str = str(rec.get("sub", "PRODUCCIÓN GRAN FORMATO"))

        draw.text((x0 + 16, y0 + 17), f"ID: {code_str}", fill=(56, 189, 248))
        draw.text((x1 - 95, y0 + 17), f"#{idx+1:02d}/{len(records):02d}", fill=(226, 232, 240))

        # Si hay imagen base, colocar miniatura a la izquierda
        if base_img is not None:
            thumb = base_img.convert("RGB").resize((84, 84), Image.Resampling.LANCZOS)
            sheet.paste(thumb, (x0 + 16, y0 + 60))
            tx = x0 + 112
        else:
            tx = x0 + 18

        draw.text((tx, y0 + 66), label_str[:24], fill=(15, 23, 42))
        draw.text((tx, y0 + 94), sub_str[:28], fill=(71, 85, 105))
        draw.text((tx, y0 + 122), "CONTORNO: CUTCONTOUR", fill=(236, 0, 140))

        # Matriz QR / DataMatrix determinista basada en el código variable
        qr_size = 64
        qx0 = x1 - qr_size - 16
        qy0 = y0 + 64
        cells = 8
        cell_px = qr_size // cells
        seed = sum((i + 1) * ord(ch) for i, ch in enumerate(code_str))
        for qr_r in range(cells):
            for qr_c in range(cells):
                is_border = qr_r in (0, cells - 1) or qr_c in (0, cells - 1)
                bit = ((seed >> ((qr_r * cells + qr_c) % 16)) ^ (qr_r * 3 + qr_c)) & 1
                if is_border or bit:
                    draw.rectangle(
                        [
                            qx0 + qr_c * cell_px,
                            qy0 + qr_r * cell_px,
                            qx0 + (qr_c + 1) * cell_px - 1,
                            qy0 + (qr_r + 1) * cell_px - 1,
                        ],
                        fill=(15, 23, 42),
                    )

    return {
        "total_records": len(records),
        "cols": cols,
        "rows": rows,
        "sheet_image": sheet,
    }
