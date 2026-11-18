# ==============================================================================
# ApexRIP SoftRIP Edition — Capturador de Protocolo Nativo (.PRN) en Red LAN
# Permite ejecutar en PC 3 y recibir los bytes EXACTOS desde Wasatch (Mutoh 9100)
# o RasterLink 7 (Mimaki 11111) sin necesitar permisos en PC 1 ni PC 2.
# ==============================================================================

$ErrorActionPreference = "Continue"
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SpoolDir = Join-Path $BaseDir "output_spool"
if (!(Test-Path $SpoolDir)) { New-Item -ItemType Directory -Path $SpoolDir | Out-Null }

# Detectar IP LAN de esta PC (PC 3)
$LocalIp = "127.0.0.1"
try {
    $ipObj = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
        $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*"
    } | Select-Object -First 1
    if ($ipObj) { $LocalIp = $ipObj.IPAddress }
} catch {}

Clear-Host
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  APEXRIP - CAPTURADOR DE PROTOCOLO NATIVO (.PRN) PARA DRIVER DIRECTO" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  IP de ESTA PC en tu red local:  $LocalIp" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Que impresora quieres capturar ahora?" -ForegroundColor White
Write-Host "    [1] Mutoh ValueJet VJ-1624   (Puerto TCP 9100  - desde Wasatch)" -ForegroundColor Cyan
Write-Host "    [2] Mimaki UJV100-160        (Puerto TCP 11111 - desde RasterLink 7)" -ForegroundColor Green
Write-Host ""
$Choice = Read-Host "Elige 1 o 2 y pulsa Enter"

if ($Choice -eq "2") {
    $Port = 11111
    $Tag = "mimaki_11111"
    $Label = "Mimaki UJV100-160 (Puerto 11111)"
} else {
    $Port = 9100
    $Tag = "mutoh_9100"
    $Label = "Mutoh VJ-1624 (Puerto 9100)"
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  ESCUCHANDO: $Label en 0.0.0.0:$Port" -ForegroundColor Green
Write-Host "  1. En Wasatch (PC 1) o RasterLink (PC 2), apunta temporalmente a:" -ForegroundColor White
Write-Host "        IP: $LocalIp    Puerto: $Port" -ForegroundColor Yellow
Write-Host "  2. Imprime un cuadro PEQUENO de 5 x 5 cm (ej. Cian/Magenta/Amarillo/Negro)." -ForegroundColor White
Write-Host "  3. El archivo .prn se guardara automaticamente en:" -ForegroundColor White
Write-Host "        $SpoolDir" -ForegroundColor Cyan
Write-Host "  4. Luego vuelve a poner la IP real de la impresora." -ForegroundColor Gray
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "Esperando conexion en $LocalIp`:$Port ... (Ctrl+C para salir)" -ForegroundColor Green
Write-Host ""

$Listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Port)
try {
    $Listener.Start()
} catch {
    Write-Host "[ERROR] No se pudo abrir el puerto $Port`: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Si Windows Firewall pregunta, pulsa 'Permitir acceso'." -ForegroundColor Yellow
    pause
    exit 1
}

try {
    while ($true) {
        $Client = $Listener.AcceptTcpClient()
        $Remote = $Client.Client.RemoteEndPoint.ToString()
        $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $OutFile = Join-Path $SpoolDir "captura_${Tag}_${Timestamp}.prn"
        Write-Host "[CAPTURANDO] Conexion desde $Remote -> $OutFile" -ForegroundColor Yellow

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
            # Fin de transmision
        } finally {
            $FileStream.Flush()
            $FileStream.Close()
            $NetStream.Close()
            $Client.Close()
        }

        if ($TotalBytes -gt 0) {
            Write-Host "[EXITO] Capturados $TotalBytes bytes -> $OutFile" -ForegroundColor Green
            $HeadLen = [Math]::Min(64, $TotalBytes)
            $RawArr = [System.IO.File]::ReadAllBytes($OutFile)
            $Slice = $RawArr[0..($HeadLen - 1)]
            $HexPreview = ($Slice | ForEach-Object { $_.ToString("X2") }) -join " "
            Write-Host "  Primeros $HeadLen bytes (HEX): $HexPreview" -ForegroundColor DarkCyan
            Start-Process explorer.exe $SpoolDir
        } else {
            Remove-Item $OutFile -ErrorAction SilentlyContinue
            Write-Host "[AVISO] Conexion vacia (0 bytes)." -ForegroundColor DarkYellow
        }
        Write-Host ""
        Write-Host "Listo para otra captura en $LocalIp`:$Port ..." -ForegroundColor Green
    }
} finally {
    $Listener.Stop()
}
