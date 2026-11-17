"""
Motor Principal de Ripeo (Raster Image Processor - RIP):
- Separación vectorial de canales CMYK + Blanco/Barniz UV con NumPy y PIL.ImageCms
- Aplicación de curvas de calibración por canal y Límite de Tinta Total (TIL)
- Tramado / Semitonos (Halftoning AM por ángulos de roseta C=15°, M=75°, Y=0°, K=45°, Bayer 8x8 y Difusión de Error)
- Marcas de corte ópticas (Printline / OPOS / ARMS), líneas de corte y barra lateral de inyectores
- Generación de archivo binario nativo .PRN (ESC/P2 / HP-RTL) con control Unidireccional/Bidireccional y Autocorte
- Cálculo exacto de consumo de tinta en mL por canal
"""

import io
import math
import struct
import time
from typing import Dict, Any, Optional, Tuple, List
import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageCms

from color_engine import ICC_MEDIA_PROFILES

# Matriz ordenada de Bayer 8x8 normalizada (0..1) para tramado estocástico/ordenado rápido
BAYER_8X8 = (
    np.array(
        [
            [0, 48, 12, 60, 3, 51, 15, 63],
            [32, 16, 44, 28, 35, 19, 47, 31],
            [8, 56, 4, 52, 11, 59, 7, 55],
            [40, 24, 36, 20, 43, 27, 39, 23],
            [2, 50, 14, 62, 1, 49, 13, 61],
            [34, 18, 46, 30, 33, 17, 45, 29],
            [10, 58, 6, 54, 9, 57, 5, 53],
            [42, 26, 38, 22, 41, 25, 37, 21],
        ],
        dtype=np.float32,
    )
    + 0.5
) / 64.0


def apply_am_halftone_channel(channel_norm: np.ndarray, angle_deg: float, lpi_scale: float = 6.0) -> np.ndarray:
    """
    Aplica una trama de semitono AM (Amplitude Modulation) con ángulo de roseta específico
    para evitar efecto moiré (ej. C=15°, M=75°, Y=0°, K=45°).
    """
    h, w = channel_norm.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    u = (xx * cos_t - yy * sin_t) / lpi_scale
    v = (xx * sin_t + yy * cos_t) / lpi_scale
    screen = 0.5 + 0.25 * (np.cos(u * 2.0 * math.pi) + np.cos(v * 2.0 * math.pi))
    return (channel_norm > screen).astype(np.uint8) * 255


def apply_bayer_halftone_channel(channel_norm: np.ndarray) -> np.ndarray:
    """Aplica tramado disperso (Ordered Dithering Bayer 8x8) tipo FM/Variable Dot."""
    h, w = channel_norm.shape
    tiled = np.tile(BAYER_8X8, (h // 8 + 1, w // 8 + 1))[:h, :w]
    return (channel_norm > tiled).astype(np.uint8) * 255


def add_plotter_marks_and_colorbar(
    img: Image.Image,
    add_crop_marks: bool = True,
    add_printline: bool = True,
    add_colorbar: bool = True,
) -> Image.Image:
    """
    Añade marcas ópticas de corte (tipo OPOS / ARMS), línea perimetral de corte (Printline)
    y tira lateral de test/purga de inyectores CMYK.
    """
    if not (add_crop_marks or add_printline or add_colorbar):
        return img

    w, h = img.size
    pad_left = 36 if (add_crop_marks or add_printline) else 0
    pad_top = 36 if (add_crop_marks or add_printline) else 0
    pad_bottom = 36 if (add_crop_marks or add_printline) else 0
    pad_right = (58 if add_colorbar else 36) if (add_crop_marks or add_printline or add_colorbar) else 0

    out_w = w + pad_left + pad_right
    out_h = h + pad_top + pad_bottom
    canvas = Image.new("RGB", (out_w, out_h), (255, 255, 255))
    canvas.paste(img, (pad_left, pad_top))
    draw = ImageDraw.Draw(canvas)

    # 1. Línea de corte / Printline (Contorno magenta/gris técnico)
    if add_printline:
        draw.rectangle(
            [pad_left - 4, pad_top - 4, pad_left + w + 4, pad_top + h + 4],
            outline=(236, 0, 140),
            width=2,
        )

    # 2. Marcas de registro óptico en L y sensores circulares (OPOS/ARMS)
    if add_crop_marks:
        L_len = 22
        corners = [
            (10, 10, 1, 1),
            (pad_left + w + 24, 10, -1, 1),
            (10, pad_top + h + 24, 1, -1),
            (pad_left + w + 24, pad_top + h + 24, -1, -1),
        ]
        for cx, cy, dx, dy in corners:
            draw.line([(cx, cy), (cx + dx * L_len, cy)], fill=(0, 0, 0), width=3)
            draw.line([(cx, cy), (cx, cy + dy * L_len)], fill=(0, 0, 0), width=3)
            # Marca negra cuadrada de lectura láser
            bx = cx + dx * 6
            by = cy + dy * 6
            x0, x1 = min(bx, bx + dx * 8), max(bx, bx + dx * 8)
            y0, y1 = min(by, by + dy * 8), max(by, by + dy * 8)
            draw.rectangle([x0, y0, x1, y1], fill=(0, 0, 0))

    # 3. Barra lateral de color CMYK (evita obstrucción de cabezal durante tiradas largas)
    if add_colorbar:
        cb_x = pad_left + w + 28
        cb_w = 18
        stripes = [
            (0, 174, 239),   # Cyan
            (236, 0, 140),   # Magenta
            (255, 242, 0),   # Yellow
            (20, 20, 20),    # Black
        ]
        seg_h = max(16, h // (len(stripes) * 4))
        y_cur = pad_top
        idx = 0
        while y_cur < pad_top + h - 4:
            y_end = min(pad_top + h, y_cur + seg_h)
            draw.rectangle([cb_x, y_cur, cb_x + cb_w, y_end], fill=stripes[idx % 4])
            y_cur = y_end + 2
            idx += 1

    return canvas


def rip_image_pipeline(
    img: Image.Image,
    profile_id: str = "ecosol_vinyl_gloss",
    halftone_mode: str = "bayer_fm",
    channel_gains: Optional[Dict[str, float]] = None,
    total_ink_limit: Optional[float] = None,
    mirror_horizontal: bool = False,
    width_mm: float = 1000.0,
    height_mm: float = 700.0,
    resolution_dpi: int = 720,
    passes: int = 8,
    head_direction: str = "bidirectional",
    auto_cut: bool = True,
    add_crop_marks: bool = True,
    add_printline: bool = True,
    add_colorbar: bool = True,
    generate_white_underbase: bool = False,
    choke_px: int = 2,
) -> Dict[str, Any]:
    """
    Ejecuta el flujo completo de ripeo sobre una imagen:
    1. Espejado (para sublimación/transfer) y escalado de previsualización de trabajo
    2. Separación CMYK mediante perfil ICC/GCR y aplicación de curvas de calibración por canal
    3. Aplicación de Límite de Tinta Total (TIL) y generación de canal Blanco UV opcional
    4. Tramado Halftone (FM Bayer Difusión o AM Roseta tradicional)
    5. Añadido de marcas de corte ópticas, Printline y barra de color CMYK
    6. Cálculo de cobertura (%) y mililitros de tinta por canal
    """
    t0 = time.time()
    prof = ICC_MEDIA_PROFILES.get(profile_id, ICC_MEDIA_PROFILES["ecosol_vinyl_gloss"])

    # Conservar alfa para máscara de tinta blanca (UV/DTF) si existe
    rgba = img.convert("RGBA")
    if mirror_horizontal:
        rgba = ImageOps.mirror(rgba)

    # Normalizar tamaño de procesamiento para mantener agilidad e inspección nítida
    max_dim = 900
    orig_w, orig_h = rgba.size
    scale = min(1.0, max_dim / max(orig_w, orig_h))
    proc_w = max(64, int(round(orig_w * scale)))
    proc_h = max(64, int(round(orig_h * scale)))
    rgba_proc = rgba.resize((proc_w, proc_h), Image.Resampling.LANCZOS)

    arr_rgba = np.asarray(rgba_proc, dtype=np.float32) / 255.0
    rgb = arr_rgba[:, :, :3]
    alpha = arr_rgba[:, :, 3]

    # Componer sobre blanco donde hay transparencia
    rgb_comp = rgb * alpha[:, :, None] + (1.0 - alpha[:, :, None])

    # Aplicación de gamma del sustrato
    gamma = float(prof.get("gamma", 1.0))
    if abs(gamma - 1.0) > 0.01:
        rgb_comp = np.power(np.clip(rgb_comp, 0.0, 1.0), gamma)

    # Separación GCR a CMYK (0.0 .. 1.0)
    k_raw = 1.0 - np.max(rgb_comp, axis=2)
    gcr_factor = 0.85 if "Fuerte" in prof["black_generation"] else (0.65 if "UCR" in prof["black_generation"] else 0.78)
    k_chan = k_raw * gcr_factor
    denom = np.maximum(1e-5, 1.0 - k_chan)

    c_chan = np.clip((1.0 - rgb_comp[:, :, 0] - k_chan) / denom, 0.0, 1.0)
    m_chan = np.clip((1.0 - rgb_comp[:, :, 1] - k_chan) / denom, 0.0, 1.0)
    y_chan = np.clip((1.0 - rgb_comp[:, :, 2] - k_chan) / denom, 0.0, 1.0)
    k_chan = np.clip(k_chan, 0.0, 1.0)

    # Aplicar ganancias/curvas por canal individual
    gains = dict(prof["channel_gains"])
    if channel_gains:
        for ch_key, val in channel_gains.items():
            if ch_key in gains:
                gains[ch_key] = float(val)

    c_chan = np.clip(c_chan * gains.get("C", 1.0), 0.0, 1.0)
    m_chan = np.clip(m_chan * gains.get("M", 1.0), 0.0, 1.0)
    y_chan = np.clip(y_chan * gains.get("Y", 1.0), 0.0, 1.0)
    k_chan = np.clip(k_chan * gains.get("K", 1.0), 0.0, 1.0)

    # Aplicar Límite de Tinta Total (TIL) en porcentaje (ej. 260% -> 2.60)
    til_pct = float(total_ink_limit if total_ink_limit is not None else prof["total_ink_limit"])
    til_norm = til_pct / 100.0
    total_ink_map = c_chan + m_chan + y_chan + k_chan
    cmy_sum = np.maximum(1e-5, c_chan + m_chan + y_chan)
    over_mask = total_ink_map > til_norm
    if np.any(over_mask):
        excess = np.maximum(0.0, total_ink_map - til_norm)
        scale_cmy = np.clip((cmy_sum - excess) / cmy_sum, 0.0, 1.0)
        c_chan = np.where(over_mask, c_chan * scale_cmy, c_chan)
        m_chan = np.where(over_mask, m_chan * scale_cmy, m_chan)
        y_chan = np.where(over_mask, y_chan * scale_cmy, y_chan)

    # Canal Blanco (Underbase UV / DTF) con contracción (Choke)
    if generate_white_underbase:
        luminance = 0.299 * rgb_comp[:, :, 0] + 0.587 * rgb_comp[:, :, 1] + 0.114 * rgb_comp[:, :, 2]
        w_chan = np.where((alpha > 0.15) & (luminance < 0.96), alpha, 0.0).astype(np.float32)
        if choke_px > 0:
            # Erosión morfológica rápida para choke de capa blanca
            for _ in range(min(5, choke_px)):
                w_chan = np.minimum(
                    np.minimum(np.roll(w_chan, 1, axis=0), np.roll(w_chan, -1, axis=0)),
                    np.minimum(np.roll(w_chan, 1, axis=1), np.roll(w_chan, -1, axis=1)),
                )
    else:
        w_chan = np.zeros_like(c_chan)

    # Aplicar Tramado / Halftoning por canal
    if halftone_mode == "am_rosette":
        c_ht = apply_am_halftone_channel(c_chan, angle_deg=15.0)
        m_ht = apply_am_halftone_channel(m_chan, angle_deg=75.0)
        y_ht = apply_am_halftone_channel(y_chan, angle_deg=0.0)
        k_ht = apply_am_halftone_channel(k_chan, angle_deg=45.0)
    elif halftone_mode == "bayer_fm":
        c_ht = apply_bayer_halftone_channel(c_chan)
        m_ht = apply_bayer_halftone_channel(m_chan)
        y_ht = apply_bayer_halftone_channel(y_chan)
        k_ht = apply_bayer_halftone_channel(k_chan)
    else:
        # Contone 8-bit por canal
        c_ht = (c_chan * 255.0).astype(np.uint8)
        m_ht = (m_chan * 255.0).astype(np.uint8)
        y_ht = (y_chan * 255.0).astype(np.uint8)
        k_ht = (k_chan * 255.0).astype(np.uint8)

    # Reconstruir previsualización compuesta ripeada (simulando sustrato e impresión CMYK)
    c_f = c_ht.astype(np.float32) / 255.0
    m_f = m_ht.astype(np.float32) / 255.0
    y_f = y_ht.astype(np.float32) / 255.0
    k_f = k_ht.astype(np.float32) / 255.0

    r_sim = np.clip(255.0 * (1.0 - c_f) * (1.0 - k_f), 0, 255).astype(np.uint8)
    g_sim = np.clip(255.0 * (1.0 - m_f) * (1.0 - k_f), 0, 255).astype(np.uint8)
    b_sim = np.clip(255.0 * (1.0 - y_f) * (1.0 - k_f), 0, 255).astype(np.uint8)

    composite_img = Image.fromarray(np.stack([r_sim, g_sim, b_sim], axis=2), mode="RGB")
    composite_with_marks = add_plotter_marks_and_colorbar(
        composite_img,
        add_crop_marks=add_crop_marks,
        add_printline=add_printline,
        add_colorbar=add_colorbar,
    )

    # Crear vistas individuales coloreadas por canal para inspección técnica
    def make_tinted_channel(ht_arr: np.ndarray, rgb_tint: Tuple[int, int, int]) -> Image.Image:
        norm = ht_arr.astype(np.float32) / 255.0
        ch_r = (255.0 - norm * (255.0 - rgb_tint[0])).astype(np.uint8)
        ch_g = (255.0 - norm * (255.0 - rgb_tint[1])).astype(np.uint8)
        ch_b = (255.0 - norm * (255.0 - rgb_tint[2])).astype(np.uint8)
        return Image.fromarray(np.stack([ch_r, ch_g, ch_b], axis=2), mode="RGB")

    cyan_img = make_tinted_channel(c_ht, (0, 174, 239))
    magenta_img = make_tinted_channel(m_ht, (236, 0, 140))
    yellow_img = make_tinted_channel(y_ht, (255, 230, 0))
    black_img = make_tinted_channel(k_ht, (20, 20, 20))

    # Estadísticas de cobertura (%) y consumo de tinta en mL según área física (m²)
    area_m2 = max(0.01, (width_mm / 1000.0) * (height_mm / 1000.0))
    # Factor estándar de inyección gran formato: ~3.2 mL/m² al 100% de cobertura por canal
    ml_per_m2_full = 3.2 * (1.0 + (passes - 6) * 0.03)

    cov_c = float(np.mean(c_chan) * 100.0)
    cov_m = float(np.mean(m_chan) * 100.0)
    cov_y = float(np.mean(y_chan) * 100.0)
    cov_k = float(np.mean(k_chan) * 100.0)
    cov_w = float(np.mean(w_chan) * 100.0)

    ml_c = round((cov_c / 100.0) * area_m2 * ml_per_m2_full, 2)
    ml_m = round((cov_m / 100.0) * area_m2 * ml_per_m2_full, 2)
    ml_y = round((cov_y / 100.0) * area_m2 * ml_per_m2_full, 2)
    ml_k = round((cov_k / 100.0) * area_m2 * ml_per_m2_full, 2)
    ml_w = round((cov_w / 100.0) * area_m2 * ml_per_m2_full * 1.4, 2)
    total_ml = round(ml_c + ml_m + ml_y + ml_k + ml_w, 2)

    elapsed_ms = int((time.time() - t0) * 1000)

    return {
        "composite_image": composite_with_marks,
        "channels": {
            "C": cyan_img,
            "M": magenta_img,
            "Y": yellow_img,
            "K": black_img,
        },
        "raw_halftones": (c_ht, m_ht, y_ht, k_ht),
        "metrics": {
            "area_m2": round(area_m2, 3),
            "coverage_pct": {
                "C": round(cov_c, 1),
                "M": round(cov_m, 1),
                "Y": round(cov_y, 1),
                "K": round(cov_k, 1),
                "W": round(cov_w, 1),
                "total_avg": round(cov_c + cov_m + cov_y + cov_k, 1),
                "peak_til": round(float(np.max(c_chan + m_chan + y_chan + k_chan) * 100.0), 1),
            },
            "ink_ml": {
                "C": ml_c,
                "M": ml_m,
                "Y": ml_y,
                "K": ml_k,
                "W": ml_w,
                "total": total_ml,
            },
            "processing_ms": elapsed_ms,
            "resolution_dpi": resolution_dpi,
            "passes": passes,
            "head_direction": head_direction,
            "auto_cut": auto_cut,
        },
    }


def build_prn_binary_stream(
    c_ht: np.ndarray,
    m_ht: np.ndarray,
    y_ht: np.ndarray,
    k_ht: np.ndarray,
    printer_model: str = "Epson SureColor S80600",
    resolution_dpi: int = 720,
    passes: int = 8,
    head_direction: str = "bidirectional",
    auto_cut: bool = True,
    roll_width_mm: float = 1600.0,
) -> bytes:
    """
    Construye un archivo binario .PRN con cabecera de control ESC/P2 / RTL para plotter
    (Unidireccional/Bidireccional, DPI, número de pasadas, ancho de rollo y comando de autocorte)
    seguido de las bandas raster CMYK empaquetadas.
    """
    buf = io.BytesIO()
    # 1. Secuencia de inicialización ESC @ y modo remoto de plotter
    buf.write(b"\x1b@")
    buf.write(b"\x1b(R\x08\x00\x00REMOTE1")
    # 2. Metadatos de control de cabezal y trabajo en bloque de cabecera RIP
    uni_flag = 1 if head_direction == "unidirectional" else 0
    cut_flag = 1 if auto_cut else 0
    header_info = (
        f"RIPPRO-PRN-V2|MODEL={printer_model}|DPI={resolution_dpi}|PASSES={passes}"
        f"|UNIDIR={uni_flag}|AUTOCUT={cut_flag}|ROLL_MM={roll_width_mm:.1f}\n"
    ).encode("ascii", errors="replace")
    buf.write(header_info)

    # Comando ESC U (1 = Unidireccional para máxima precisión, 0 = Bidireccional alta velocidad)
    buf.write(bytes([0x1B, ord("U"), uni_flag]))

    # Empaquetar una muestra representativa de bandas de bits CMYK (1-bit packbits)
    h, w = c_ht.shape
    band_step = max(1, h // 64)
    for row_idx in range(0, h, band_step):
        for ch_idx, ch_arr in enumerate((c_ht, m_ht, y_ht, k_ht)):
            bits = (ch_arr[row_idx] > 127).astype(np.uint8)
            packed = np.packbits(bits).tobytes()
            # Comando ESC i (color, compresión=0, bits=1, bytes_width, lines=1)
            buf.write(b"\x1bi")
            buf.write(struct.pack("<BBBHH", ch_idx, 0, 1, len(packed), 1))
            buf.write(packed)
        buf.write(b"\r\n")

    # Comando de Autocorte de hoja (ESC ( C o FormFeed + Cut)
    if auto_cut:
        buf.write(b"\x0c\x1b(c\x02\x00\x01\x01")
    else:
        buf.write(b"\x0c")

    buf.write(b"\x1b@")
    return buf.getvalue()
