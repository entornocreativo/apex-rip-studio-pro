# ApexRIP Studio Pro v2.4 — Software RIP de Gran Formato (Python + Electron)

Software profesional de procesamiento de imágenes rasterizadas (**RIP**) para plotters e impresoras digitales de gran formato (**Ecosolvente, Sublimación Textil y UV LED**).

## Características Implementadas

1. **Gestión de Color y Precisión (`backend/color_engine.py`)**:
   - **Generador de Atlas de Colores**: Genera hojas de muestras de color (parches con recetas CMYK, Hex y CIE Lab) con marcas de corte listas para imprimir en el material real y emparejar tonos exactos.
   - **Manejo de Perfiles ICC y Calibración por Canal**: Perfiles para Vinilo Ecosolvente, Lona Frontlit, Papel de Sublimación y Rígidos UV, con ajuste de curvas/ganancias por canal individual (`C`, `M`, `Y`, `K`, `Lc`, `Lm`), generación de negro (`GCR`/`UCR`) y control de **Límite de Tinta Total (TIL)**.
   - **Importación CIE L\*a\*b\* y PANTONE®**: Conversión matemática CIE Lab (D50/D65) → XYZ → sRGB / CMYK de dispositivo y cálculo de desviación cromática $\Delta E_{00}$ (CIEDE2000).

2. **Flujo de Trabajo y Automatización (`backend/workflow_engine.py`)**:
   - **Colas de Impresión Múltiples y Cola Maestra**: Gestión simultánea de múltiples colas (*Cola A: Ecosolvente*, *Cola B: Sublimación*, *Cola C: UV LED*) y **Cola Maestra** para almacenar trabajos ya ripeados listos para reimpresión inmediata.
   - **Impresión de Datos Variables (VDP)**: Personalización seriada con texto variable, numeración, códigos QR/DataMatrix y línea de troquelado (`CutContour`).
   - **Composición (Auto-Nesting) y Panelación (Tiling)**:
     - *Nesting*: Optimización automática de piezas en el ancho del rollo para ahorrar metros lineales.
     - *Panelación*: División de murales/gráficas gigantes en paneles con solapamiento configurable (*overlap* en mm) y giro alterno de 180° en paneles pares.

3. **Control de Hardware y Spooler Directo (`backend/hardware_spooler.py` & `backend/rip_engine.py`)**:
   - Soporte multimarca (**Epson SureColor, Roland TrueVIS, Mimaki UCJV/JV, Mutoh XpertJet**).
   - Control de cabezal **Unidireccional / Bidireccional**, número de pasadas (4 a 16 pasadas), **Autocorte de hoja (Sheet Cut)**, **Línea de corte (Printline)**, **Marcas ópticas (OPOS/ARMS)** y **Barra lateral de inyectores CMYK**.
   - Salida directa por **Red TCP/IP (Socket Raw Puerto 9100)**, **USB directo (`/dev/usb/lp0`)** o exportación de binario nativo **`.PRN` (ESC/P2 / RTL)**.

## Ejecución en Escritorio (Local)

### Opción 1: Lanzador directo en Python
```bash
python3 desktop_launcher.py
```

### Opción 2: Ventana nativa con Electron
```bash
npm install
npm start
```
