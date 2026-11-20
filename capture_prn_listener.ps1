# ==============================================================================
# ApexRIP SoftRIP Edition — Capturador de Protocolo Nativo (.PRN) en Red LAN
# Permite ejecutar en PC 3 y recibir los bytes EXACTOS desde Wasatch (Mutoh 9100)
# o RasterLink 7 (Mimaki 11111) sin necesitar permisos en PC 1 ni PC 2.
# ==============================================================================

$ErrorActionPreference = "Continue"
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SpoolDir = Join-Path $BaseDir "output_spool"
if (!(Test-Path $SpoolDir)) { New-Item -ItemType Directory -Path $SpoolDir | Out-Null }

# Detectar IP LAN de esta PC (Compatible con Windows 7 PowerShell 2.0 y Windows 10/11)
$LocalIp = "127.0.0.1"
try {
    $addrs = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) | Where-Object {
        $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
        $_.IPAddressToString -notlike "127.*" -and
        $_.IPAddressToString -notlike "169.254.*"
    }
    if ($addrs) {
        if ($addrs -is [array]) { $LocalIp = $addrs[0].IPAddressToString }
        else { $LocalIp = $addrs.IPAddressToString }
    }
} catch {}

Clear-Host
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  APEXRIP - CAPTURADOR DE ARCHIVO .PRN (LOCAL 127.0.0.1 O RED LAN)" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  IP en la misma PC (sin Firewall):  127.0.0.1" -ForegroundColor Green
Write-Host "  IP de esta PC en la red local:     $LocalIp" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Que impresora quieres capturar ahora?" -ForegroundColor White
Write-Host "    [1] Mutoh ValueJet VJ-1624   (Puerto TCP 9100  - desde Wasatch)" -ForegroundColor Cyan
Write-Host "    [2] Mimaki UJV100-160        (Puerto TCP 11111 - desde RasterLink 7)" -ForegroundColor Green
Write-Host ""
$Choice = Read-Host "Elige 1 o 2 y pulsa Enter"

if ($Choice -eq "2") {
    $Port = 11111
    $RealPrinterIp = "192.168.1.73"
    $Tag = "mimaki_11111"
    $Label = "Mimaki UJV100-160 (Puerto 11111 -> Relay a $RealPrinterIp)"
} else {
    $Port = 9100
    $RealPrinterIp = "192.168.1.240"
    $Tag = "mutoh_9100"
    $Label = "Mutoh VJ-1624 (Puerto 9100 -> Relay a $RealPrinterIp)"
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  ESCUCHANDO: $Label en 0.0.0.0:$Port" -ForegroundColor Green
Write-Host "  1. En Wasatch (PC 1) o RasterLink (PC 2), apunta temporalmente a:" -ForegroundColor White
Write-Host "        IP: $LocalIp    Puerto: $Port" -ForegroundColor Yellow
Write-Host "     (Recuerda pulsar OK en todas las ventanas de Setup para guardar)" -ForegroundColor Gray
Write-Host "  2. Imprime un cuadro PEQUENO de 5 x 5 cm." -ForegroundColor White
Write-Host "  3. Este puente reenvia el saludo a la impresora real ($RealPrinterIp)" -ForegroundColor White
Write-Host "     y guarda el archivo .prn automaticamente en:" -ForegroundColor White
Write-Host "        $SpoolDir" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# Intentar abrir el puerto en el Firewall de Windows de esta PC (PC 3)
try {
    $RuleName = "ApexRIP_PRN_Capture_$Port"
    $null = & netsh advfirewall firewall delete rule name="$RuleName" 2>$null
    $fwOut = & netsh advfirewall firewall add rule name="$RuleName" dir=in action=allow protocol=TCP localport=$Port profile=any 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Regla de Firewall abierta en PC 3 para el puerto TCP $Port" -ForegroundColor Green
    } else {
        Write-Host "[AVISO] Si no conecta, abre CMD como Administrador y ejecuta:" -ForegroundColor Yellow
        Write-Host "  netsh advfirewall firewall add rule name=ApexRIP_$Port dir=in action=allow protocol=TCP localport=$Port profile=any" -ForegroundColor Cyan
    }
} catch {}

Write-Host "Esperando conexion en $LocalIp`:$Port ... (Ctrl+C para salir)" -ForegroundColor Green
Write-Host ""

$Listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Port)
try {
    $Listener.Start()
} catch {
    Write-Host "[ERROR] No se pudo abrir el puerto $Port`: $($_.Exception.Message)" -ForegroundColor Red
    pause
    exit 1
}

try {
    while ($true) {
        $Client = $Listener.AcceptTcpClient()
        $Remote = $Client.Client.RemoteEndPoint.ToString()
        $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $OutFile = Join-Path $SpoolDir "captura_${Tag}_${Timestamp}.prn"
        Write-Host "[CONECTADO] Conexion entrante desde $Remote -> Guardando en $OutFile" -ForegroundColor Yellow

        $NetStream = $Client.GetStream()
        $FileStream = [System.IO.File]::Create($OutFile)
        $Buffer = New-Object byte[] 65536
        $ReplyBuf = New-Object byte[] 65536
        $TotalBytes = 0

        # Conectar en paralelo a la impresora real (Relay transparente) para responder handshakes
        $PrinterClient = $null
        $PrinterStream = $null
        try {
            $PrinterClient = New-Object System.Net.Sockets.TcpClient
            $iar = $PrinterClient.BeginConnect($RealPrinterIp, $Port, $null, $null)
            if ($iar.AsyncWaitHandle.WaitOne(2000, $false) -and $PrinterClient.Connected) {
                $PrinterClient.EndConnect($iar)
                $PrinterStream = $PrinterClient.GetStream()
                Write-Host "  [RELAY ACTIVO] Conectado a impresora real $RealPrinterIp`:$Port para responder handshakes" -ForegroundColor Cyan
            }
        } catch {}

        $LastActivity = [DateTime]::UtcNow
        try {
            while ($Client.Connected) {
                $DidWork = $false
                if ($NetStream.DataAvailable) {
                    $Read = $NetStream.Read($Buffer, 0, $Buffer.Length)
                    if ($Read -le 0) { break }
                    $FileStream.Write($Buffer, 0, $Read)
                    $TotalBytes += $Read
                    $LastActivity = [DateTime]::UtcNow
                    $DidWork = $true
                    if ($PrinterStream -ne $null) {
                        try { $PrinterStream.Write($Buffer, 0, $Read) } catch {}
                    }
                }
                if ($PrinterStream -ne $null -and $PrinterStream.DataAvailable) {
                    $PRead = $PrinterStream.Read($ReplyBuf, 0, $ReplyBuf.Length)
                    if ($PRead -gt 0) {
                        $NetStream.Write($ReplyBuf, 0, $PRead)
                        $LastActivity = [DateTime]::UtcNow
                        $DidWork = $true
                    }
                }
                if (-not $DidWork) {
                    Start-Sleep -Milliseconds 15
                    # Comprobar si el cliente cerro la conexion o si pasaron 8 seg de inactividad tras recibir datos
                    if ($TotalBytes -gt 0 -and (([DateTime]::UtcNow - $LastActivity).TotalSeconds -gt 8)) {
                        break
                    }
                    if ($TotalBytes -eq 0 -and (([DateTime]::UtcNow - $LastActivity).TotalSeconds -gt 15)) {
                        break
                    }
                }
            }
        } catch {} finally {
            $FileStream.Flush()
            $FileStream.Close()
            if ($PrinterStream -ne $null) { try { $PrinterStream.Close() } catch {} }
            if ($PrinterClient -ne $null) { try { $PrinterClient.Close() } catch {} }
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
            Write-Host "[AVISO] Conexion cerrada sin datos (0 bytes)." -ForegroundColor DarkYellow
        }
        Write-Host ""
        Write-Host "Listo para otra captura en $LocalIp`:$Port ..." -ForegroundColor Green
    }
} finally {
    $Listener.Stop()
}
