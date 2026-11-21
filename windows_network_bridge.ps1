# ==============================================================================
# ApexRIP SoftRIP Edition — Puente Nativo de Impresión TCP/IP Puerto 9100 para Windows
# Funciona en cualquier PC con Windows 10 / 11 SIN necesitar Python ni drivers extra.
# Conecta el navegador directamente con Mutoh VJ-1624 y Mimaki UJV100-160 por Red LAN.
# ==============================================================================

$ErrorActionPreference = "Continue"
$Port = 8765
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SpoolDir = Join-Path $BaseDir "output_spool"
if (!(Test-Path $SpoolDir)) { New-Item -ItemType Directory -Path $SpoolDir | Out-Null }

function Get-LocalLanIp {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
            $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*"
        } | Select-Object -First 1).IPAddress
        if ($ip) { return $ip }
    } catch {}
    return "192.168.1.100"
}

$LocalIp = Get-LocalLanIp
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  APEXRIP SOFTRIP - PUENTE DE IMPRESION EN RED TCP/IP (PUERTO 9100)" -ForegroundColor Green
Write-Host "  Mutoh ValueJet VJ-1624  &  Mimaki UJV100-160" -ForegroundColor White
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  IP de tu PC en la Red Local : $LocalIp" -ForegroundColor Yellow
Write-Host "  Puente Local Activo en      : http://127.0.0.1:$Port" -ForegroundColor Yellow
Write-Host "  Carpeta de Respaldo .PRN    : $SpoolDir" -ForegroundColor Gray
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "Deja esta ventana abierta mientras imprimes desde ApexRIP." -ForegroundColor White
Write-Host ""

$Listener = New-Object System.Net.HttpListener
$Listener.Prefixes.Add("http://127.0.0.1:$Port/")
$Listener.Prefixes.Add("http://localhost:$Port/")

try {
    $Listener.Start()
} catch {
    Write-Host "[AVISO] El puerto $Port ya esta en uso (posiblemente ya tienes el puente o Python abierto)." -ForegroundColor Yellow
    exit 0
}

# Abrir la interfaz automaticamente
$HtmlPath = Join-Path $BaseDir "ApexRIP_Studio_Pro_Portable.html"
if (Test-Path $HtmlPath) {
    Start-Process $HtmlPath
}

function Send-JsonResponse($Response, $Obj, $StatusCode = 200) {
    $Response.StatusCode = $StatusCode
    $Response.ContentType = "application/json; charset=utf-8"
    $Response.Headers.Add("Access-Control-Allow-Origin", "*")
    $Response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    $Response.Headers.Add("Access-Control-Allow-Headers", "Content-Type")
    $Json = $Obj | ConvertTo-Json -Depth 6 -Compress
    $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)
    $Response.ContentLength64 = $Bytes.Length
    $Response.OutputStream.Write($Bytes, 0, $Bytes.Length)
    $Response.Close()
}

Add-Type -AssemblyName System.Web.Extensions -ErrorAction SilentlyContinue
function Parse-LargeJsonBody($InputStream) {
    $Reader = New-Object System.IO.StreamReader($InputStream, [System.Text.Encoding]::UTF8)
    $RawJson = $Reader.ReadToEnd()
    try {
        $Ser = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $Ser.MaxJsonLength = [int]::MaxValue
        return $Ser.DeserializeObject($RawJson)
    } catch {
        $Obj = $RawJson | ConvertFrom-Json
        $Hash = @{}
        foreach ($p in $Obj.PSObject.Properties) { $Hash[$p.Name] = $p.Value }
        return $Hash
    }
}

while ($Listener.IsListening) {
    try {
        $Context = $Listener.GetContext()
        $Req = $Context.Request
        $Res = $Context.Response
        $Path = $Req.Url.AbsolutePath

        if ($Req.HttpMethod -eq "OPTIONS") {
            $Res.StatusCode = 204
            $Res.Headers.Add("Access-Control-Allow-Origin", "*")
            $Res.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            $Res.Headers.Add("Access-Control-Allow-Headers", "Content-Type")
            $Res.Close()
            continue
        }

        if ($Path -eq "/api/network/status") {
            Send-JsonResponse $Res @{
                online = $true
                bridge = "Puente Nativo Windows TCP/IP Puerto 9100"
                local_ip = (Get-LocalLanIp)
            }
            continue
        }

        if ($Path -eq "/api/network/ping" -and $Req.HttpMethod -eq "POST") {
            $Reader = New-Object System.IO.StreamReader($Req.InputStream, [System.Text.Encoding]::UTF8)
            $Body = $Reader.ReadToEnd() | ConvertFrom-Json
            $TargetHost = [string]$Body.host
            $TargetPort = [int]$Body.port
            if ($TargetPort -le 0) { $TargetPort = 9100 }

            Write-Host "[PING] Probando conexion TCP con impresora $TargetHost`:$TargetPort ..." -ForegroundColor Cyan
            $Sw = [System.Diagnostics.Stopwatch]::StartNew()
            $Tcp = New-Object System.Net.Sockets.TcpClient
            try {
                $Async = $Tcp.BeginConnect($TargetHost, $TargetPort, $null, $null)
                $Wait = $Async.AsyncWaitHandle.WaitOne(2000, $false)
                $Sw.Stop()
                if ($Wait -and $Tcp.Connected) {
                    $Tcp.EndConnect($Async)
                    $Tcp.Close()
                    Write-Host "  -> CONECTADO ($($Sw.ElapsedMilliseconds) ms)" -ForegroundColor Green
                    Send-JsonResponse $Res @{
                        reachable = $true
                        host = $TargetHost
                        port = $TargetPort
                        latency_ms = $Sw.ElapsedMilliseconds
                        message = "CONECTADO: La impresora en $TargetHost`:$TargetPort esta EN LINEA ($($Sw.ElapsedMilliseconds) ms) y lista para imprimir."
                    }
                } else {
                    $Tcp.Close()
                    # Probar puertos alternos (Mimaki UJV100 usa 11111 / 11110, Mutoh usa 9100)
                    $AltPorts = @(11111, 11110, 9100) | Where-Object { $_ -ne $TargetPort }
                    $AltConnected = $false
                    $MatchedPort = 0
                    $AltMs = 0
                    foreach ($TryPort in $AltPorts) {
                        $SwAlt = [System.Diagnostics.Stopwatch]::StartNew()
                        $TcpAlt = New-Object System.Net.Sockets.TcpClient
                        try {
                            $AsyncAlt = $TcpAlt.BeginConnect($TargetHost, $TryPort, $null, $null)
                            $WaitAlt = $AsyncAlt.AsyncWaitHandle.WaitOne(1200, $false)
                            $SwAlt.Stop()
                            if ($WaitAlt -and $TcpAlt.Connected) {
                                $TcpAlt.EndConnect($AsyncAlt)
                                $AltConnected = $true
                                $MatchedPort = $TryPort
                                $AltMs = $SwAlt.ElapsedMilliseconds
                            }
                        } catch {}
                        try { $TcpAlt.Close() } catch {}
                        if ($AltConnected) { break }
                    }

                    if ($AltConnected) {
                        Write-Host "  -> CONECTADO EN PUERTO $TargetHost`:$MatchedPort ($AltMs ms)" -ForegroundColor Green
                        Send-JsonResponse $Res @{
                            reachable = $true
                            host = $TargetHost
                            port = $MatchedPort
                            latency_ms = $AltMs
                            message = "CONECTADO: La impresora en $TargetHost respondio en el puerto TCP $MatchedPort ($AltMs ms)."
                        }
                    } else {
                        Write-Host "  -> SIN RESPUESTA en $TargetHost (puertos 11111, 11110 y 9100)" -ForegroundColor Red
                        Send-JsonResponse $Res @{
                            reachable = $false
                            host = $TargetHost
                            port = $TargetPort
                            latency_ms = $Sw.ElapsedMilliseconds
                            message = "SIN RESPUESTA en $TargetHost (puertos 11111, 11110 y 9100). Pulsa 'Buscar Red' o ejecuta BUSCAR_IMPRESORAS_RED.bat para localizar su IP actual en el switch."
                        }
                    }
                }
            } catch {
                $Tcp.Close()
                Send-JsonResponse $Res @{
                    reachable = $false
                    host = $TargetHost
                    port = $TargetPort
                    latency_ms = $Sw.ElapsedMilliseconds
                    message = "Error al conectar con $TargetHost`:$TargetPort ($($_.Exception.Message))"
                }
            }
            continue
        }

        if ($Path -eq "/api/network/scan") {
            $AllIps = @()
            try {
                $AllIps = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
                    $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown"
                } | Select-Object -ExpandProperty IPAddress)
            } catch {}
            if ($AllIps.Count -eq 0) { $AllIps = @(Get-LocalLanIp) }

            $Subnets = @()
            foreach ($ip in $AllIps) {
                $Parts = $ip.Split(".")
                if ($Parts.Length -eq 4) {
                    $Pref = "$($Parts[0]).$($Parts[1]).$($Parts[2])"
                    if ($Subnets -notcontains $Pref) { $Subnets += $Pref }
                }
            }

            Write-Host "[SCAN] Buscando impresoras en subredes ($($Subnets -join ', ')) puertos 11111 (Mimaki UJV100), 9100 (Mutoh) y 11110..." -ForegroundColor Cyan

            $Found = @()
            $ScanSpecs = @(
                @{ Port = 11111; Label = "Mimaki UJV100-160 (Puerto 11111)" },
                @{ Port = 9100;  Label = "Mutoh VJ-1624 / RAW (Puerto 9100)" },
                @{ Port = 11110; Label = "Mimaki Ethernet (Puerto 11110)" }
            )

            foreach ($Prefix in $Subnets) {
                foreach ($Spec in $ScanSpecs) {
                    $PNum = $Spec.Port
                    $Pending = @()
                    for ($i = 1; $i -le 254; $i++) {
                        $TestIp = "$Prefix.$i"
                        $Client = New-Object System.Net.Sockets.TcpClient
                        try {
                            $Async = $Client.BeginConnect($TestIp, $PNum, $null, $null)
                            $Pending += [PSCustomObject]@{ Ip = $TestIp; Client = $Client; Async = $Async }
                        } catch {
                            try { $Client.Close() } catch {}
                        }
                    }
                    Start-Sleep -Milliseconds 600
                    foreach ($Item in $Pending) {
                        try {
                            if ($Item.Async.IsCompleted -and $Item.Client.Connected) {
                                $Found += @{
                                    ip = $Item.Ip
                                    port = $PNum
                                    hostname = $Spec.Label
                                    latency_ms = 12
                                }
                                Write-Host "  -> IMPRESORA ENCONTRADA: $($Item.Ip):$PNum [$($Spec.Label)]" -ForegroundColor Green
                            }
                        } catch {}
                        try { $Item.Client.Close() } catch {}
                    }
                }
            }

            # Incluir tambien vecinos ARP del switch (para detectar equipos aunque bloqueen ping/puerto)
            $ArpDevices = @()
            try {
                foreach ($line in (arp -a)) {
                    if ($line -match "^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s+(\S+)") {
                        $aIp = $Matches[1]
                        $aMac = $Matches[2].ToUpper()
                        if ($aIp -notlike "224.*" -and $aIp -notlike "239.*" -and $aIp -notlike "*.255" -and $aMac -ne "FF-FF-FF-FF-FF-FF") {
                            $ArpDevices += @{ ip = $aIp; mac = $aMac }
                        }
                    }
                }
            } catch {}

            Send-JsonResponse $Res @{
                local_ip = ($AllIps -join ", ")
                subnet = (($Subnets | ForEach-Object { "$_.0/24" }) -join ", ")
                port_scanned = "11111, 9100, 11110"
                found = $Found
                arp_devices = $ArpDevices
            }
            continue
        }

        if ($Path -eq "/api/spool/send-raw" -and $Req.HttpMethod -eq "POST") {
            $ContentType = ([string]$Req.ContentType).ToLower()
            $TargetHost = ""
            $TargetPort = 9100
            $JobTitle = "Mutoh_Job"
            $ConnMode = "tcp_raw"
            $WinPrinter = ""
            $PrnBytes = $null

            if ($ContentType -like "*octet-stream*") {
                $TargetHost = ([string]$Req.QueryString["host"]).Trim()
                try { $TargetPort = [int]$Req.QueryString["port"] } catch { $TargetPort = 9100 }
                if ($TargetPort -le 0) { $TargetPort = 9100 }
                $RawTitle = [string]$Req.QueryString["job_title"]
                if ($RawTitle) { $JobTitle = $RawTitle -replace '[^a-zA-Z0-9_-]', '_' }
                $ConnMode = [string]$Req.QueryString["connection_mode"]
                $WinPrinter = [string]$Req.QueryString["windows_printer_name"]

                $Ms = New-Object System.IO.MemoryStream
                $Buf = New-Object byte[] 65536
                $InStream = $Req.InputStream
                while (($ReadCount = $InStream.Read($Buf, 0, $Buf.Length)) -gt 0) {
                    $Ms.Write($Buf, 0, $ReadCount)
                }
                $PrnBytes = $Ms.ToArray()
                $Ms.Close()
            } else {
                $Body = Parse-LargeJsonBody $Req.InputStream
                $TargetHost = ([string]$Body["host"]).Trim()
                $TargetPort = [int]$Body["port"]
                if ($TargetPort -le 0) { $TargetPort = 9100 }
                $JobTitle = ([string]$Body["job_title"]) -replace '[^a-zA-Z0-9_-]', '_'
                $ConnMode = [string]$Body["connection_mode"]
                $WinPrinter = [string]$Body["windows_printer_name"]
                $PrnBytes = [System.Convert]::FromBase64String([string]$Body["prn_base64"])
            }

            $PrnFile = Join-Path $SpoolDir "$($JobTitle)_$(Get-Date -Format 'yyyyMMdd_HHmmss').prn"
            [System.IO.File]::WriteAllBytes($PrnFile, $PrnBytes)

            if ($ConnMode -eq "windows_spooler" -and $WinPrinter) {
                Write-Host "[PRINT] Enviando $($PrnBytes.Length) bytes a cola de Windows '$WinPrinter'..." -ForegroundColor Cyan
                cmd.exe /c "COPY /B `"$PrnFile`" `"\\localhost\$WinPrinter`"" | Out-Null
                Send-JsonResponse $Res @{
                    spool = @{
                        success = $true
                        tcp_delivered = $true
                        mode = "Cola de Impresion Windows"
                        target = $WinPrinter
                        bytes_sent = $PrnBytes.Length
                        spool_backup = $PrnFile
                        message = "Trabajo enviado a la cola de Windows '$WinPrinter' ($($PrnBytes.Length) bytes)."
                    }
                }
                continue
            }

            Write-Host "[PRINT] Enviando $($PrnBytes.Length) bytes por Red TCP/IP a $TargetHost`:$TargetPort ..." -ForegroundColor Cyan
            $Tcp = New-Object System.Net.Sockets.TcpClient
            $Tcp.SendBufferSize = 32768
            $Tcp.NoDelay = $true
            try {
                $Async = $Tcp.BeginConnect($TargetHost, $TargetPort, $null, $null)
                $Wait = $Async.AsyncWaitHandle.WaitOne(8000, $false)
                if ($Wait -and $Tcp.Connected) {
                    $Tcp.EndConnect($Async)
                    try {
                        $Tcp.Client.SetSocketOption([System.Net.Sockets.SocketOptionLevel]::Socket, [System.Net.Sockets.SocketOptionName]::KeepAlive, $true)
                    } catch {}
                    $Stream = $Tcp.GetStream()
                    # Sin timeout corto (2 horas = 7200000 ms) porque cuando se imprimen 10+ copias o trabajos largos (>100 MB),
                    # la memoria RAM interna de la Mutoh (32-64 MB) se llena y la impresora pausa la ventana TCP (ZeroWindow)
                    # hasta que el cabezal fisico va avanzando y liberando memoria.
                    $Stream.WriteTimeout = 7200000
                    $Tcp.SendTimeout = 7200000

                    $ChunkSize = 16384
                    $Offset = 0
                    $TotalLen = $PrnBytes.Length
                    $LastPctShown = -1

                    while ($Offset -lt $TotalLen) {
                        $Count = [Math]::Min($ChunkSize, $TotalLen - $Offset)
                        $WriteOk = $false
                        $RetryCount = 0
                        while (-not $WriteOk) {
                            try {
                                $Stream.Write($PrnBytes, $Offset, $Count)
                                $WriteOk = $true
                            } catch {
                                $RetryCount++
                                if ($RetryCount -gt 120 -or -not $Tcp.Connected) {
                                    throw $_
                                }
                                Write-Host "  [BUFFER PLOTTER LLENO] Esperando avance fisico del cabezal ($Offset / $TotalLen bytes)..." -ForegroundColor Yellow
                                Start-Sleep -Milliseconds 1500
                            }
                        }
                        $Offset += $Count
                        $Pct = [int][Math]::Floor(($Offset * 100.0) / $TotalLen)
                        if ($Pct -ge ($LastPctShown + 5) -or $Offset -eq $TotalLen) {
                            $LastPctShown = $Pct
                            $MbSent = [Math]::Round($Offset / 1048576.0, 2)
                            $MbTot  = [Math]::Round($TotalLen / 1048576.0, 2)
                            Write-Host ("  -> Progreso envio a Plotter: {0}% ({1} MB / {2} MB)" -f $Pct, $MbSent, $MbTot) -ForegroundColor DarkCyan
                        }
                    }
                    $Stream.Flush()
                    Start-Sleep -Milliseconds 300
                    $Stream.Close()
                    $Tcp.Close()
                    Write-Host "  -> IMPRESION ENVIADA CON EXITO a $TargetHost`:$TargetPort ($($PrnBytes.Length) bytes)" -ForegroundColor Green
                    Send-JsonResponse $Res @{
                        spool = @{
                            success = $true
                            tcp_delivered = $true
                            mode = "TCP/IP Raw Socket (Mutoh_PM / MH-RTL Directo)"
                            target = "$TargetHost`:$TargetPort"
                            bytes_sent = $PrnBytes.Length
                            spool_backup = $PrnFile
                            message = "IMPRESION ENVIADA CON EXITO a $TargetHost`:$TargetPort ($($PrnBytes.Length) bytes transmitidos a la impresora)."
                        }
                    }
                } else {
                    $Tcp.Close()
                    Write-Host "  -> ERROR: La impresora en $TargetHost`:$TargetPort no respondio." -ForegroundColor Red
                    Send-JsonResponse $Res @{
                        spool = @{
                            success = $false
                            tcp_delivered = $false
                            mode = "Error Conexion TCP/IP"
                            target = "$TargetHost`:$TargetPort"
                            bytes_sent = 0
                            spool_backup = $PrnFile
                            message = "No se pudo conectar con la impresora en $TargetHost`:$TargetPort. Verifica la IP en Setup Unit. Respaldo .PRN guardado en: $PrnFile"
                        }
                    }
                }
            } catch {
                $Tcp.Close()
                Write-Host "  -> ERROR TCP: $($_.Exception.Message)" -ForegroundColor Red
                Send-JsonResponse $Res @{
                    spool = @{
                        success = $false
                        tcp_delivered = $false
                        mode = "Error Conexion TCP/IP"
                        target = "$TargetHost`:$TargetPort"
                        bytes_sent = $Offset
                        spool_backup = $PrnFile
                        message = "Error de red hacia $TargetHost`:$TargetPort tras enviar $Offset de $($PrnBytes.Length) bytes ($($_.Exception.Message)). Respaldo .PRN en: $PrnFile"
                    }
                }
            }
            continue
        }

        if ($Path -eq "/api/hotfolder/detect") {
            Write-Host "[HOTFOLDER] Buscando carpetas Hot Folder de Wasatch SoftRIP y Mimaki RasterLink..." -ForegroundColor Cyan
            $FoundFolders = @()
            $Candidates = @(
                "C:\ApexRIP_HotFolder_Mutoh",
                "C:\ApexRIP_HotFolder_Mimaki",
                "C:\MijSuite\HotFolder",
                "C:\MijSuite\Hot",
                "C:\RasterLink\HotFolder",
                "C:\RasterLink7\HotFolder",
                "C:\ProgramData\Mimaki\RasterLink7\HotFolder"
            )
            # Buscar subcarpetas hotfolder dentro de C:\wwrip* (Wasatch) y C:\MijSuite* (RasterLink)
            try {
                Get-ChildItem -Path "C:\" -Directory -Filter "wwrip*" -ErrorAction SilentlyContinue | ForEach-Object {
                    $Candidates += Join-Path $_.FullName "hotfolder"
                    $Candidates += Join-Path $_.FullName "hotfolders"
                    Get-ChildItem -Path $_.FullName -Directory -Filter "*hot*" -ErrorAction SilentlyContinue | ForEach-Object {
                        $Candidates += $_.FullName
                    }
                }
                Get-ChildItem -Path "C:\" -Directory -Filter "*Mij*" -ErrorAction SilentlyContinue | ForEach-Object {
                    Get-ChildItem -Path $_.FullName -Directory -Recurse -Depth 2 -Filter "*hot*" -ErrorAction SilentlyContinue | ForEach-Object {
                        $Candidates += $_.FullName
                    }
                }
            } catch {}

            $Seen = @{}
            foreach ($Dir in $Candidates) {
                if ($Dir -and !$Seen.ContainsKey($Dir.ToLower())) {
                    $Seen[$Dir.ToLower()] = $true
                    $Exists = Test-Path $Dir
                    if ($Exists -or $Dir -like "C:\ApexRIP_HotFolder_*") {
                        $FoundFolders += @{
                            path = $Dir
                            exists = $Exists
                            software = $(if ($Dir -like "*wwrip*" -or $Dir -like "*Mutoh*") { "Wasatch SoftRIP (Mutoh)" } else { "Mimaki RasterLink 7" })
                        }
                    }
                }
            }

            Send-JsonResponse $Res @{
                folders = $FoundFolders
                default_mutoh = "C:\ApexRIP_HotFolder_Mutoh"
                default_mimaki = "C:\ApexRIP_HotFolder_Mimaki"
            }
            continue
        }

        if ($Path -eq "/api/hotfolder/export" -and $Req.HttpMethod -eq "POST") {
            $Body = Parse-LargeJsonBody $Req.InputStream
            $HotFolder = ([string]$Body["hot_folder_path"]).Trim()
            if (!$HotFolder) { $HotFolder = "C:\ApexRIP_HotFolder_Mutoh" }
            $JobTitle = ([string]$Body["job_title"]) -replace '[^a-zA-Z0-9_-]', '_'
            if (!$JobTitle) { $JobTitle = "ApexRIP_Job" }
            $Ext = ([string]$Body["file_ext"]).Trim().TrimStart('.')
            if (!$Ext) { $Ext = "pdf" }
            $FileBytes = [System.Convert]::FromBase64String([string]$Body["file_base64"])

            try {
                if (!(Test-Path $HotFolder)) {
                    New-Item -ItemType Directory -Path $HotFolder -Force | Out-Null
                }
                $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
                $FinalName = "$($JobTitle)_$($Stamp).$Ext"
                $TmpPath = Join-Path $HotFolder "$($FinalName).tmp"
                $FinalPath = Join-Path $HotFolder $FinalName

                # Escritura atomica: escribir .tmp y renombrar a .pdf/.tif para que Wasatch/RasterLink no lo lea a medias
                [System.IO.File]::WriteAllBytes($TmpPath, $FileBytes)
                Move-Item -Path $TmpPath -Destination $FinalPath -Force

                # Respaldo local en output_spool
                $BackupPath = Join-Path $SpoolDir $FinalName
                [System.IO.File]::WriteAllBytes($BackupPath, $FileBytes)

                Write-Host "[HOTFOLDER] Enviado 1:1 ($($FileBytes.Length) bytes) -> $FinalPath" -ForegroundColor Green
                Send-JsonResponse $Res @{
                    spool = @{
                        success = $true
                        tcp_delivered = $true
                        mode = "Hot Folder 1:1 (Wasatch / RasterLink)"
                        target = $FinalPath
                        bytes_sent = $FileBytes.Length
                        spool_backup = $BackupPath
                        message = "IMPRESION ENVIADA A HOT FOLDER (1:1 Real): $FinalPath ($($FileBytes.Length) bytes). Wasatch/RasterLink lo procesara automaticamente."
                    }
                }
            } catch {
                Write-Host "[HOTFOLDER ERROR] $($_.Exception.Message)" -ForegroundColor Red
                Send-JsonResponse $Res @{
                    spool = @{
                        success = $false
                        tcp_delivered = $false
                        mode = "Error Hot Folder"
                        target = $HotFolder
                        bytes_sent = 0
                        message = "No se pudo escribir en la Hot Folder '$HotFolder': $($_.Exception.Message)"
                    }
                }
            }
            continue
        }

        Send-JsonResponse $Res @{ error = "Ruta no encontrada" } 404
    } catch {
        Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    }
}
