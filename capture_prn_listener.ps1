# ==============================================================================
# ApexRIP SoftRIP Edition — Capturador de Protocolo Nativo (.PRN / .PRM)
# Escucha en 127.0.0.1:9100 para capturar los bytes EXACTOS que envia
# Wasatch SoftRIP (Mutoh VJ-1624) o RasterLink 7 (Mimaki UJV100-160).
# ==============================================================================

$ErrorActionPreference = "Continue"
$Port = 9100
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SpoolDir = Join-Path $BaseDir "output_spool"
if (!(Test-Path $SpoolDir)) { New-Item -ItemType Directory -Path $SpoolDir | Out-Null }

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  APEXRIP - CAPTURADOR DE PROTOCOLO NATIVO (.PRN / .PRM) PUERTO 9100" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  1. En Wasatch SoftRIP (Mutoh) o RasterLink 7 (Mimaki), cambia" -ForegroundColor White
Write-Host "     temporalmente la IP de destino a:  127.0.0.1  (Puerto 9100)" -ForegroundColor Yellow
Write-Host "  2. Imprime un cuadro PEQUENO de prueba (ej. 5 x 5 cm)." -ForegroundColor White
Write-Host "  3. Este capturador guardara el archivo .prn real en:" -ForegroundColor White
Write-Host "     $SpoolDir" -ForegroundColor Cyan
Write-Host "  4. Luego vuelve a poner la IP real de tu impresora en Wasatch/RasterLink." -ForegroundColor Gray
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "Esperando conexion en 127.0.0.1:$Port ... (Ctrl+C para salir)" -ForegroundColor Green
Write-Host ""

$Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try {
    $Listener.Start()
} catch {
    Write-Host "[ERROR] No se pudo abrir el puerto 9100 en 127.0.0.1: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Cierra cualquier otro programa que use el puerto 9100 e intentalo de nuevo." -ForegroundColor Yellow
    pause
    exit 1
}

try {
    while ($true) {
        $Client = $Listener.AcceptTcpClient()
        $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $OutFile = Join-Path $SpoolDir "captura_prn_$Timestamp.prn"
        Write-Host "[CAPTURANDO] Conexion entrante detectada... guardando en $OutFile" -ForegroundColor Yellow

        $NetStream = $Client.GetStream()
        $NetStream.ReadTimeout = 10000
        $FileStream = [System.IO.File]::Create($OutFile)
        $Buffer = New-Object byte[] 65536
        $TotalBytes = 0

        try {
            while ($true) {
                $Read = $NetStream.Read($Buffer, 0, $Buffer.Length)
                if ($Read -le 0) { break }
                $FileStream.Write($Buffer, 0, $Read)
                $TotalBytes += $Read
            }
        } catch [System.IO.IOException] {
            # Timeout o cierre limpio del socket al terminar el envio
        } finally {
            $FileStream.Flush()
            $FileStream.Close()
            $NetStream.Close()
            $Client.Close()
        }

        if ($TotalBytes -gt 0) {
            Write-Host "[EXITO] Capturados $TotalBytes bytes -> $OutFile" -ForegroundColor Green
            $HeadLen = [Math]::Min(64, $TotalBytes)
            $FirstBytes = [System.IO.File]::ReadAllBytes($OutFile)[0..($HeadLen - 1)]
            $HexPreview = ($FirstBytes | ForEach-Object { $_.ToString("X2") }) -join " "
            Write-Host "  Primeros $HeadLen bytes (HEX): $HexPreview" -ForegroundColor DarkCyan
            Write-Host "  Abriendo carpeta output_spool para que puedas subir este .prn..." -ForegroundColor White
            Start-Process explorer.exe $SpoolDir
        } else {
            Remove-Item $OutFile -ErrorAction SilentlyContinue
            Write-Host "[AVISO] Conexion vacia (0 bytes)." -ForegroundColor DarkYellow
        }
        Write-Host ""
        Write-Host "Listo para otra captura en 127.0.0.1:$Port ..." -ForegroundColor Green
    }
} finally {
    $Listener.Stop()
}
