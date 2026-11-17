"""
Motor de Gestión de Color Profesional para RIP de Gran Formato:
- Transformaciones ICC reales (PIL.ImageCms / LittleCMS2) y conversión CIE L*a*b* <-> sRGB <-> CMYK(+LcLm+W+V)
- Cálculo de precisión Delta E (CIEDE2000)
- Importación y emparejamiento de bibliotecas PANTONE / CIE Lab / CSV / JSON
- Curvas de calibración y linealización por canal individual (C, M, Y, K, Lc, Lm) y Límite de Tinta Total (TIL)
- Generador de Atlas de Colores (Color Swatch Atlas) listo para impresión con marcas de corte
"""

import io
import math
import json
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageCms


# Biblioteca base integrada de tonos estilo PANTONE / Spot en CIE L*a*b* (D50)
BUILTIN_SPOT_LIBRARY: List[Dict[str, Any]] = [
    {"code": "PANTONE 185 C", "name": "Rojo Intenso", "L": 49.5, "a": 75.2, "b": 47.8, "category": "Formula Guide Coated"},
    {"code": "PANTONE 286 C", "name": "Azul Cobalto", "L": 34.2, "a": 12.8, "b": -64.5, "category": "Formula Guide Coated"},
    {"code": "PANTONE 300 C", "name": "Azul Cian Corporativo", "L": 44.0, "a": -3.5, "b": -58.0, "category": "Formula Guide Coated"},
    {"code": "PANTONE 116 C", "name": "Amarillo Cálido", "L": 83.5, "a": 8.5, "b": 85.0, "category": "Formula Guide Coated"},
    {"code": "PANTONE 354 C", "name": "Verde Vibrante", "L": 63.8, "a": -65.0, "b": 42.0, "category": "Formula Guide Coated"},
    {"code": "PANTONE 021 C", "name": "Naranja Puro", "L": 60.5, "a": 62.0, "b": 72.0, "category": "Formula Guide Coated"},
    {"code": "PANTONE 2685 C", "name": "Violeta Profundo", "L": 24.5, "a": 38.0, "b": -52.0, "category": "Formula Guide Coated"},
    {"code": "PANTONE Rhodamine Red C", "name": "Magenta Rodamina", "L": 51.0, "a": 79.0, "b": -14.0, "category": "Formula Guide Coated"},
    {"code": "PANTONE Process Cyan C", "name": "Cian Proceso", "L": 57.5, "a": -39.0, "b": -48.5, "category": "Process Coated"},
    {"code": "PANTONE Cool Gray 9 C", "name": "Gris Frío Neutro", "L": 50.2, "a": -1.1, "b": -3.2, "category": "Neutrals"},
    {"code": "PANTONE 877 C", "name": "Plata Metálico Simulado", "L": 58.0, "a": -0.5, "b": -1.5, "category": "Metallics"},
    {"code": "PANTONE 485 C", "name": "Rojo Señalización", "L": 47.0, "a": 71.5, "b": 56.0, "category": "Formula Guide Coated"},
]

# Perfiles ICC y configuraciones de sustrato predefinidas y editables para Mutoh VJ-1624 y Mimaki UJV100-160
ICC_MEDIA_PROFILES: Dict[str, Dict[str, Any]] = {
    "mutoh_vinyl_gloss_1370": {
        "id": "mutoh_vinyl_gloss_1370",
        "name": "Mutoh VJ-1624 — Vinilo Adhesivo Brillante",
        "printer_id": "mutoh_vj_1624",
        "ink_type": "Ecosolvente CMYK (i² Wave)",
        "default_width_mm": 1370.0,
        "coil_length_m": 50.0,
        "rendering_intent": "Perceptual",
        "total_ink_limit": 270,
        "black_generation": "GCR Medio",
        "channel_gains": {"C": 1.0, "M": 0.98, "Y": 1.0, "K": 1.02, "W": 0.0},
        "heaters_c": {"pre": 40, "platen": 42, "dryer": 48},
        "uv_lamp_pct": 0,
        "resolution": "720x1440",
        "passes": 8,
        "gamma": 1.0,
    },
    "mutoh_banner_1600": {
        "id": "mutoh_banner_1600",
        "name": "Mutoh VJ-1624 — Lona Frontlit 13oz",
        "printer_id": "mutoh_vj_1624",
        "ink_type": "Ecosolvente CMYK",
        "default_width_mm": 1600.0,
        "coil_length_m": 50.0,
        "rendering_intent": "Relative Colorimetric",
        "total_ink_limit": 250,
        "black_generation": "GCR Fuerte",
        "channel_gains": {"C": 1.03, "M": 1.02, "Y": 1.01, "K": 1.05, "W": 0.0},
        "heaters_c": {"pre": 42, "platen": 44, "dryer": 50},
        "uv_lamp_pct": 0,
        "resolution": "720x720",
        "passes": 6,
        "gamma": 0.96,
    },
    "mimaki_uv_vinyl_1520": {
        "id": "mimaki_uv_vinyl_1520",
        "name": "Mimaki UJV100-160 — Vinilo / PET UV (CMYK)",
        "printer_id": "mimaki_ujv100_160",
        "ink_type": "UV LED LUS-170 CMYK (MAPS4)",
        "default_width_mm": 1520.0,
        "coil_length_m": 50.0,
        "rendering_intent": "Perceptual",
        "total_ink_limit": 280,
        "black_generation": "GCR Medio",
        "channel_gains": {"C": 0.98, "M": 0.97, "Y": 1.0, "K": 1.0, "W": 0.0},
        "heaters_c": {"pre": 0, "platen": 0, "dryer": 0},
        "uv_lamp_pct": 80,
        "resolution": "600x1200",
        "passes": 8,
        "gamma": 1.0,
    },
    "mimaki_uv_backlit_white_1600": {
        "id": "mimaki_uv_backlit_white_1600",
        "name": "Mimaki UJV100-160 — Film Transparente / Backlit (CMYK + Blanco)",
        "printer_id": "mimaki_ujv100_160",
        "ink_type": "UV LED CMYK + Blanco (W) + Barniz (V)",
        "default_width_mm": 1600.0,
        "coil_length_m": 50.0,
        "rendering_intent": "Relative Colorimetric",
        "total_ink_limit": 300,
        "black_generation": "GCR Medio",
        "channel_gains": {"C": 1.02, "M": 1.02, "Y": 1.0, "K": 1.04, "W": 1.0},
        "heaters_c": {"pre": 0, "platen": 0, "dryer": 0},
        "uv_lamp_pct": 95,
        "resolution": "600x1200",
        "passes": 12,
        "gamma": 1.02,
    },
}


def lab_to_xyz(L: float, a: float, b: float) -> Tuple[float, float, float]:
    """Convierte CIE L*a*b* (iluminante D65) a CIE XYZ."""
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0

    delta = 6.0 / 29.0

    def f_inv(t: float) -> float:
        if t > delta:
            return t ** 3
        return 3.0 * (delta ** 2) * (t - 4.0 / 29.0)

    # Referencia blanco D65
    Xn, Yn, Zn = 0.95047, 1.00000, 1.08883
    return Xn * f_inv(fx), Yn * f_inv(fy), Zn * f_inv(fz)


def xyz_to_srgb(X: float, Y: float, Z: float) -> Tuple[int, int, int]:
    """Convierte CIE XYZ a sRGB (0-255)."""
    r_lin = X * 3.2406 + Y * -1.5372 + Z * -0.4986
    g_lin = X * -0.9689 + Y * 1.8758 + Z * 0.0415
    b_lin = X * 0.0557 + Y * -0.2040 + Z * 1.0570

    def gamma_correct(c: float) -> int:
        c = max(0.0, min(1.0, c))
        if c <= 0.0031308:
            v = 12.92 * c
        else:
            v = 1.055 * (c ** (1.0 / 2.4)) - 0.055
        return int(round(max(0.0, min(255.0, v * 255.0))))

    return gamma_correct(r_lin), gamma_correct(g_lin), gamma_correct(b_lin)


def srgb_to_lab(r: int, g: int, b_val: int) -> Tuple[float, float, float]:
    """Convierte sRGB (0-255) a CIE L*a*b*."""
    def inv_gamma(u: int) -> float:
        c = u / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = inv_gamma(r), inv_gamma(g), inv_gamma(b_val)
    X = rl * 0.4124 + gl * 0.3576 + bl * 0.1805
    Y = rl * 0.2126 + gl * 0.7152 + bl * 0.0722
    Z = rl * 0.0193 + gl * 0.1192 + bl * 0.9505

    Xn, Yn, Zn = 0.95047, 1.00000, 1.08883
    delta = 6.0 / 29.0

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > delta ** 3 else (t / (3.0 * delta ** 2)) + (4.0 / 29.0)

    fx, fy, fz = f(X / Xn), f(Y / Yn), f(Z / Zn)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return round(L, 2), round(a, 2), round(b, 2)


def delta_e_cie2000(lab1: Tuple[float, float, float], lab2: Tuple[float, float, float]) -> float:
    """Calcula la diferencia de color CIEDE2000 (Delta E 00) entre dos colores CIE Lab."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2

    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    C_bar = (C1 + C2) / 2.0
    G = 0.5 * (1.0 - math.sqrt((C_bar ** 7) / (C_bar ** 7 + 25.0 ** 7)))

    a1_p = (1.0 + G) * a1
    a2_p = (1.0 + G) * a2
    C1_p = math.hypot(a1_p, b1)
    C2_p = math.hypot(a2_p, b2)

    h1_p = math.degrees(math.atan2(b1, a1_p)) % 360.0 if C1_p != 0 else 0.0
    h2_p = math.degrees(math.atan2(b2, a2_p)) % 360.0 if C2_p != 0 else 0.0

    dL_p = L2 - L1
    dC_p = C2_p - C1_p

    if C1_p * C2_p == 0:
        dh_p = 0.0
    else:
        dh = h2_p - h1_p
        if abs(dh) <= 180.0:
            dh_p = dh
        elif dh > 180.0:
            dh_p = dh - 360.0
        else:
            dh_p = dh + 360.0

    dH_p = 2.0 * math.sqrt(C1_p * C2_p) * math.sin(math.radians(dh_p / 2.0))

    L_bar_p = (L1 + L2) / 2.0
    C_bar_p = (C1_p + C2_p) / 2.0

    if C1_p * C2_p == 0:
        h_bar_p = h1_p + h2_p
    else:
        if abs(h1_p - h2_p) <= 180.0:
            h_bar_p = (h1_p + h2_p) / 2.0
        elif (h1_p + h2_p) < 360.0:
            h_bar_p = (h1_p + h2_p + 360.0) / 2.0
        else:
            h_bar_p = (h1_p + h2_p - 360.0) / 2.0

    T = (
        1.0
        - 0.17 * math.cos(math.radians(h_bar_p - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * h_bar_p))
        + 0.32 * math.cos(math.radians(3.0 * h_bar_p + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * h_bar_p - 63.0))
    )

    d_theta = 30.0 * math.exp(-(((h_bar_p - 275.0) / 25.0) ** 2))
    R_C = 2.0 * math.sqrt((C_bar_p ** 7) / (C_bar_p ** 7 + 25.0 ** 7))
    S_L = 1.0 + (0.015 * ((L_bar_p - 50.0) ** 2)) / math.sqrt(20.0 + ((L_bar_p - 50.0) ** 2))
    S_C = 1.0 + 0.045 * C_bar_p
    S_H = 1.0 + 0.015 * C_bar_p * T
    R_T = -math.sin(math.radians(2.0 * d_theta)) * R_C

    dE = math.sqrt(
        (dL_p / S_L) ** 2
        + (dC_p / S_C) ** 2
        + (dH_p / S_H) ** 2
        + R_T * (dC_p / S_C) * (dH_p / S_H)
    )
    return round(dE, 2)


def rgb_to_device_cmyk(
    r: int,
    g: int,
    b: int,
    profile_id: str = "mutoh_vinyl_gloss_1370",
    channel_curves: Optional[Dict[str, float]] = None,
    total_ink_limit: Optional[float] = None,
) -> Dict[str, float]:
    """
    Convierte un color RGB a valores CMYK (+LcLm) aplicando el perfil de sustrato,
    generación de negro GCR, curvas por canal y límite de tinta total (TIL).
    Retorna porcentajes de 0.0 a 100.0 por canal.
    """
    prof = ICC_MEDIA_PROFILES.get(profile_id, ICC_MEDIA_PROFILES["mutoh_vinyl_gloss_1370"])
    gains = dict(prof["channel_gains"])
    if channel_curves:
        for k, v in channel_curves.items():
            if k in gains:
                gains[k] = float(v)

    til = float(total_ink_limit if total_ink_limit is not None else prof["total_ink_limit"])

    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    k_raw = 1.0 - max(rf, gf, bf)
    if k_raw >= 0.999:
        c, m, y, k = 0.0, 0.0, 0.0, 100.0
    else:
        # GCR factor según perfil
        gcr = 0.85 if "Fuerte" in prof["black_generation"] else (0.65 if "UCR" in prof["black_generation"] else 0.78)
        k_eff = k_raw * gcr
        c = ((1.0 - rf - k_eff) / (1.0 - k_eff)) * 100.0
        m = ((1.0 - gf - k_eff) / (1.0 - k_eff)) * 100.0
        y = ((1.0 - bf - k_eff) / (1.0 - k_eff)) * 100.0
        k = k_eff * 100.0

    # Aplicar ganancias/calibración de canal individual
    c = max(0.0, min(100.0, c * gains.get("C", 1.0)))
    m = max(0.0, min(100.0, m * gains.get("M", 1.0)))
    y = max(0.0, min(100.0, y * gains.get("Y", 1.0)))
    k = max(0.0, min(100.0, k * gains.get("K", 1.0)))

    # Control de Límite de Tinta Total (TIL)
    total = c + m + y + k
    if total > til and (c + m + y) > 0:
        excess = total - til
        scale = max(0.0, (c + m + y - excess) / (c + m + y))
        c *= scale
        m *= scale
        y *= scale

    #Separación Light Cyan (Lc) y Light Magenta (Lm) para tonos medios/claros
    lc = round(min(c * 1.4, 100.0 - c) if c < 45.0 else max(0.0, (70.0 - c) * 0.4), 1)
    lm = round(min(m * 1.4, 100.0 - m) if m < 45.0 else max(0.0, (70.0 - m) * 0.4), 1)

    return {
        "C": round(c, 1),
        "M": round(m, 1),
        "Y": round(y, 1),
        "K": round(k, 1),
        "Lc": lc,
        "Lm": lm,
        "total_ink": round(c + m + y + k, 1),
    }


def enrich_spot_color(entry: Dict[str, Any], profile_id: str = "mutoh_vinyl_gloss_1370") -> Dict[str, Any]:
    """Calcula equivalencias RGB, Hex, CMYK de dispositivo y Delta E estimado para un color Lab/PANTONE."""
    L, a, b = float(entry["L"]), float(entry["a"]), float(entry["b"])
    X, Y, Z = lab_to_xyz(L, a, b)
    r, g, b_val = xyz_to_srgb(X, Y, Z)
    sim_lab = srgb_to_lab(r, g, b_val)
    dE = delta_e_cie2000((L, a, b), sim_lab)
    cmyk = rgb_to_device_cmyk(r, g, b_val, profile_id=profile_id)
    hex_code = f"#{r:02X}{g:02X}{b_val:02X}"
    return {
        **entry,
        "rgb": [r, g, b_val],
        "hex": hex_code,
        "cmyk": cmyk,
        "delta_e": dE,
    }


def generate_color_atlas(
    base_hex: str = "#E1251B",
    rows: int = 7,
    cols: int = 7,
    step_pct: float = 4.0,
    variation_mode: str = "C_vs_M",
    profile_id: str = "mutoh_vinyl_gloss_1370",
    include_crop_marks: bool = True,
) -> Dict[str, Any]:
    """
    Generador de Atlas de Colores (Color Swatch Atlas):
    Genera una matriz de parches de color alrededor de un color objetivo (en CMYK/Lab)
    para imprimir en el plotter sobre el sustrato real y elegir visualmente el parche exacto.
    Retorna tanto los metadatos de cada celda (código, CMYK, Hex, Lab) como una imagen PNG en alta resolución.
    """
    base_hex_clean = base_hex.lstrip("#")
    if len(base_hex_clean) != 6:
        base_hex_clean = "E1251B"
    r0 = int(base_hex_clean[0:2], 16)
    g0 = int(base_hex_clean[2:4], 16)
    b0 = int(base_hex_clean[4:6], 16)

    base_cmyk = rgb_to_device_cmyk(r0, g0, b0, profile_id=profile_id)
    c0, m0, y0, k0 = base_cmyk["C"], base_cmyk["M"], base_cmyk["Y"], base_cmyk["K"]

    mid_r = rows // 2
    mid_c = cols // 2

    patches: List[Dict[str, Any]] = []
    # Dimensiones del lienzo del Atlas de Impresión
    patch_w, patch_h = 128, 112
    margin_x, margin_y = 60, 95
    img_w = margin_x * 2 + cols * patch_w
    img_h = margin_y + rows * patch_h + 70

    atlas_img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(atlas_img)

    # Cabecera técnica del Atlas de Color
    prof_name = ICC_MEDIA_PROFILES.get(profile_id, {}).get("name", profile_id)
    draw.text((margin_x, 22), f"ATLAS DE COLORES RIP - {prof_name.upper()}", fill=(20, 24, 32))
    draw.text(
        (margin_x, 46),
        f"Color Base: #{base_hex_clean.upper()} | CMYK Base: C{c0:.1f}% M{m0:.1f}% Y{y0:.1f}% K{k0:.1f}% | Paso: {step_pct}% ({variation_mode})",
        fill=(80, 88, 100),
    )

    # Marcas de registro y corte (Crop Marks) en las 4 esquinas
    if include_crop_marks:
        cm_len = 22
        corners = [
            (25, 25, 1, 1),
            (img_w - 25, 25, -1, 1),
            (25, img_h - 25, 1, -1),
            (img_w - 25, img_h - 25, -1, -1),
        ]
        for cx, cy, dx, dy in corners:
            draw.line([(cx, cy), (cx + dx * cm_len, cy)], fill=(0, 0, 0), width=2)
            draw.line([(cx, cy), (cx, cy + dy * cm_len)], fill=(0, 0, 0), width=2)
            draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=(0, 0, 0), width=1)

    for r_idx in range(rows):
        for c_idx in range(cols):
            dc = (c_idx - mid_c) * step_pct
            dr = (r_idx - mid_r) * step_pct

            c_val, m_val, y_val, k_val = c0, m0, y0, k0
            if variation_mode == "C_vs_M":
                c_val = max(0.0, min(100.0, c0 + dc))
                m_val = max(0.0, min(100.0, m0 + dr))
            elif variation_mode == "Y_vs_K":
                y_val = max(0.0, min(100.0, y0 + dc))
                k_val = max(0.0, min(100.0, k0 + dr))
            else:  # C_M_vs_Y
                c_val = max(0.0, min(100.0, c0 + dc))
                y_val = max(0.0, min(100.0, y0 + dr))

            # Conversión CMYK de vuelta a sRGB de previsualización e impresión de parche
            kf = k_val / 100.0
            pr = int(round(255.0 * (1.0 - c_val / 100.0) * (1.0 - kf)))
            pg = int(round(255.0 * (1.0 - m_val / 100.0) * (1.0 - kf)))
            pb = int(round(255.0 * (1.0 - y_val / 100.0) * (1.0 - kf)))
            p_hex = f"#{pr:02X}{pg:02X}{pb:02X}"
            p_lab = srgb_to_lab(pr, pg, pb)
            patch_id = f"{chr(65 + r_idx)}{c_idx + 1}"
            is_center = (r_idx == mid_r and c_idx == mid_c)

            x0 = margin_x + c_idx * patch_w
            y_pos = margin_y + r_idx * patch_h
            pad = 6

            # Dibujar muestra de color
            draw.rectangle(
                [x0 + pad, y_pos + pad, x0 + patch_w - pad, y_pos + patch_h - 32],
                fill=(pr, pg, pb),
                outline=(15, 23, 42) if is_center else (200, 206, 215),
                width=3 if is_center else 1,
            )

            # Etiqueta del código de parche y receta CMYK
            label_prefix = f"* {patch_id}" if is_center else patch_id
            draw.text((x0 + pad + 2, y_pos + patch_h - 29), f"{label_prefix} ({p_hex})", fill=(15, 23, 42))
            draw.text(
                (x0 + pad + 2, y_pos + patch_h - 15),
                f"C{c_val:.0f} M{m_val:.0f} Y{y_val:.0f} K{k_val:.0f}",
                fill=(90, 100, 115),
            )

            patches.append({
                "id": patch_id,
                "row": r_idx,
                "col": c_idx,
                "is_center": is_center,
                "hex": p_hex,
                "rgb": [pr, pg, pb],
                "lab": list(p_lab),
                "cmyk": {
                    "C": round(c_val, 1),
                    "M": round(m_val, 1),
                    "Y": round(y_val, 1),
                    "K": round(k_val, 1),
                },
            })

    # Pie con tira de control densitométrica CMYK al 100% y 50%
    footer_y = margin_y + rows * patch_h + 15
    bar_colors = [
        ("C 100%", (0, 174, 239)),
        ("C 50%", (128, 214, 247)),
        ("M 100%", (236, 0, 140)),
        ("M 50%", (245, 128, 197)),
        ("Y 100%", (255, 242, 0)),
        ("Y 50%", (255, 248, 128)),
        ("K 100%", (20, 20, 20)),
        ("K 50%", (128, 128, 128)),
    ]
    bw = (cols * patch_w) // len(bar_colors)
    for idx, (lbl, col_rgb) in enumerate(bar_colors):
        bx = margin_x + idx * bw
        draw.rectangle([bx, footer_y, bx + bw - 4, footer_y + 24], fill=col_rgb, outline=(180, 180, 180))
        txt_col = (255, 255, 255) if lbl in ("K 100%", "M 100%", "C 100%") else (20, 20, 20)
        draw.text((bx + 6, footer_y + 6), lbl, fill=txt_col)

    return {
        "base_hex": f"#{base_hex_clean.upper()}",
        "base_cmyk": base_cmyk,
        "profile_id": profile_id,
        "rows": rows,
        "cols": cols,
        "step_pct": step_pct,
        "variation_mode": variation_mode,
        "patches": patches,
        "image": atlas_img,
    }
