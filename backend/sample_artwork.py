"""
Generador de Artes de Prueba de Alta Resolución para Gran Formato:
Crea gráficas vectoriales/raster realistas (Gráfica Vehicular Ecosolvente, Textil Sublimación, Cartelería UV)
para probar inmediatamente el motor RIP, la separación CMYK, el Atlas de Color y la Panelación.
"""

import math
from PIL import Image, ImageDraw


def create_sample_wide_format_artwork(preset: str = "motorsport_wrap", width: int = 800, height: int = 560) -> Image.Image:
    """Genera una imagen de prueba rica en degradados CMYK, tonos PANTONE, negros profundos y detalles finos."""
    img = Image.new("RGBA", (width, height), (14, 20, 34, 255))
    draw = ImageDraw.Draw(img)

    if preset == "sublimation_jersey":
        # Patrón geométrico vibrante para sublimación textil
        for y in range(height):
            t = y / max(1, height - 1)
            r = int(20 + 220 * (1 - t))
            g = int(40 + 170 * t)
            b = int(120 + 130 * math.sin(t * math.pi))
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
        for i in range(0, width + height, 48):
            draw.line([(i, 0), (i - height, height)], fill=(255, 230, 0, 190), width=8)
            draw.line([(i + 20, 0), (i - height + 20, height)], fill=(236, 0, 140, 210), width=5)
        draw.rectangle([40, height - 110, width - 40, height - 30], fill=(10, 15, 28, 235))
        draw.text((64, height - 88), "SUBLIMATION PRO SERIES - HDK DEEP BLACK & FLUORESCENT", fill=(255, 255, 255))
        draw.text((64, height - 60), "TEST DE SATURACION Y ESPEJADO AUTOMATICO DE TRANSFERENCIA", fill=(56, 189, 248))
        return img

    # Default: Gráfica Gran Formato Ecosolvente / Motorsport & Control de Color
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(12 + 30 * t)
        g = int(18 + 45 * t)
        b = int(35 + 85 * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # Bandas dinámicas en Cian, Magenta, Amarillo y Rojo PANTONE 185C
    poly_cyan = [(0, int(height * 0.65)), (int(width * 0.62), 0), (int(width * 0.78), 0), (int(width * 0.16), int(height * 0.65))]
    poly_mag = [(int(width * 0.18), int(height * 0.75)), (int(width * 0.80), 0), (int(width * 0.94), 0), (int(width * 0.32), int(height * 0.75))]
    poly_yel = [(int(width * 0.35), int(height * 0.82)), (width, int(height * 0.05)), (width, int(height * 0.22)), (int(width * 0.48), int(height * 0.82))]

    draw.polygon(poly_cyan, fill=(0, 174, 239, 255))
    draw.polygon(poly_mag, fill=(236, 0, 140, 255))
    draw.polygon(poly_yel, fill=(255, 242, 0, 255))

    # Roseta / diana de registro y precisión cromática
    cx, cy = int(width * 0.73), int(height * 0.50)
    for rad, col in [(135, (225, 37, 27)), (102, (255, 255, 255)), (72, (15, 23, 42)), (42, (0, 174, 239)), (18, (255, 242, 0))]:
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=col, outline=(255, 255, 255), width=2)

    # Parches de referencia CMYK + Gris Neutro en la parte inferior
    swatches = [
        ("C 100", (0, 174, 239)),
        ("M 100", (236, 0, 140)),
        ("Y 100", (255, 242, 0)),
        ("K 100", (15, 15, 15)),
        ("P-185C", (228, 0, 43)),
        ("P-286C", (0, 51, 160)),
        ("P-354C", (0, 177, 64)),
        ("GRIS 50", (128, 128, 128)),
    ]
    sw_w = (width - 80) // len(swatches)
    y_sw = height - 92
    for idx, (lbl, col) in enumerate(swatches):
        x0 = 40 + idx * sw_w
        draw.rectangle([x0, y_sw, x0 + sw_w - 8, y_sw + 58], fill=col, outline=(255, 255, 255), width=2)
        t_col = (15, 23, 42) if lbl in ("Y 100", "GRIS 50") else (255, 255, 255)
        draw.text((x0 + 8, y_sw + 22), lbl, fill=t_col)

    # Bloque de título técnico
    draw.rectangle([38, 34, 470, 175], fill=(10, 14, 24, 225), outline=(56, 189, 248), width=2)
    draw.text((56, 52), "APEX-RIP GRAND FORMAT TEST CHART", fill=(255, 255, 255))
    draw.text((56, 82), "ECOSOLVENTE / SUBLIMACIÓN / UV LED", fill=(56, 189, 248))
    draw.text((56, 110), "ICC Profile: Vinilo Brillante 1600mm | 720x1440 DPI", fill=(203, 213, 225))
    draw.text((56, 136), "Control: C M Y K Lc Lm + CutContour Printline", fill=(244, 114, 182))

    return img
