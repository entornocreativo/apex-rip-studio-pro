# ==============================================================================
# ApexRIP SoftRIP — Buscador Rapido de Impresoras en Red LAN (Mutoh & Mimaki)
# Escanea TODAS las subredes activas del PC en puertos 9100 (Mutoh/RAW) y
# 11110 (Mimaki Ethernet UJV100/JV100/CJV), lee conexiones activas de
# RasterLink 7 / Wasatch y muestra todos los equipos del switch (tabla ARP).
# ==============================================================================

$ErrorActionPreference = "Continue"
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutDir = Join-Path $BaseDir "output_spool"
if (!(Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
$ReportPath = Join-Path $OutDir "escaneo_red_impresoras.txt"
$Report = New-Object System.Collections.Generic.List[string]

function Log-Line($Text, $Color = "White") {
    Write-Host $Text -ForegroundColor $Color
    $Report.Add($Text)
}

Clear-Host
Log-Line "=====================================================================" "Cyan"
Log-Line "  APEXRIP - BUSQUEDA RAPIDA DE IMPRESORAS EN RED (MUTOH & MIMAKI)" "Green"
Log-Line "=====================================================================" "Cyan"
Log-Line "Fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "Gray"
Log-Line ""

# 1. Detectar todos los adaptadores IPv4 activos
$LocalIps = @()
try {
    $Adapters = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown"
    }
    foreach ($a in $Adapters) {
        $LocalIps += $a.IPAddress
        Log-Line ("  [PC] Adaptador: {0,-22} IP: {1}/{2}" -f $a.InterfaceAlias, $a.IPAddress, $a.PrefixLength) "Yellow"
    }
} catch {}

if ($LocalIps.Count -eq 0) {
    $LocalIps = @("192.168.1.100")
    Log-Line "  [PC] No se detecto adaptador automaticamente, probando subred 192.168.1.x" "Yellow"
}
Log-Line ""

# 2. Conexiones activas hacia posibles impresoras (RasterLink / Wasatch)
Log-Line "[1/4] Revisando conexiones activas (RasterLink 7 / Wasatch)..." "Cyan"
$ActiveFound = 0
try {
    $Conns = Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object {
        $_.RemoteAddress -ne "0.0.0.0" -and $_.RemoteAddress -ne "::" -and
        $_.RemoteAddress -notlike "127.*" -and
        ($_.RemotePort -in @(9100, 9101, 11110, 11111, 11112, 515, 631, 50000))
    }
    foreach ($c in $Conns) {
        $ProcName = ""
        try { $ProcName = (Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue).ProcessName } catch {}
        Log-Line ("  -> CONEXION ACTIVA: {0}:{1}  Estado={2}  App={3}" -f $c.RemoteAddress, $c.RemotePort, $c.State, $ProcName) "Green"
        $ActiveFound++
    }
} catch {}
if ($ActiveFound -eq 0) {
    Log-Line "  (Sin conexiones TCP activas a puertos 9100/11110 en este instante)" "Gray"
}
Log-Line ""

# 3. Revisar puertos de impresora TCP/IP en Windows y carpetas RasterLink/Mimaki
Log-Line "[2/4] Revisando configuracion guardada de Windows / RasterLink / Mimaki..." "Cyan"
$RegFound = 0
try {
    $PortsKey = "HKLM:\SYSTEM\CurrentControlSet\Control\Print\Monitors\Standard TCP/IP Port\Ports"
    if (Test-Path $PortsKey) {
        Get-ChildItem $PortsKey | ForEach-Object {
            $Props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if ($Props.HostName) {
                Log-Line ("  -> Puerto Windows: {0} -> IP: {1} (Puerto {2})" -f $_.PSChildName, $Props.HostName, $Props.PortNumber) "Green"
                $RegFound++
            }
        }
    }
} catch {}

# Buscar IPs en archivos ini/xml/cfg de RasterLink 7 / Mimaki / Wasatch
$SearchDirs = @(
    "C:\MijSuite",
    "C:\RasterLink7",
    "C:\ProgramData\Mimaki",
    "C:\Program Files\Mimaki",
    "C:\Program Files (x86)\Mimaki"
)
foreach ($d in $SearchDirs) {
    if (Test-Path $d) {
        try {
            $Matches = Get-ChildItem -Path $d -Recurse -Include *.ini,*.cfg,*.xml,*.txt -ErrorAction SilentlyContinue |
                Select-Object -First 80 |
                Select-String -Pattern "\b(?:192\.168|10\.|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b" -ErrorAction SilentlyContinue |
                Select-Object -First 15
            foreach ($m in $Matches) {
                $LineClean = $m.Line.Trim()
                if ($LineClean.Length -gt 95) { $LineClean = $LineClean.Substring(0, 95) }
                Log-Line ("  -> Mimaki Config ({0}): {1}" -f (Split-Path $m.Path -Leaf), $LineClean) "Magenta"
                $RegFound++
            }
        } catch {}
    }
}
if ($RegFound -eq 0) {
    Log-Line "  (No se encontraron IPs en el registro de Windows o archivos de texto Mimaki)" "Gray"
}
Log-Line ""

# 4. Escaneo paralelo rapido en TODAS las subredes activas (Puertos 9100 y 11110 + 80)
$Subnets = @()
foreach ($ip in $LocalIps) {
    $p = $ip.Split(".")
    if ($p.Length -eq 4) {
        $pref = "$($p[0]).$($p[1]).$($p[2])"
        if ($Subnets -notcontains $pref) { $Subnets += $pref }
    }
}

Log-Line "[3/4] Escaneando subredes ($($Subnets -join ', ')) en puertos 9100 (Mutoh/RAW) y 11110 (Mimaki)..." "Cyan"
$ScanPorts = @(
    @{ Port = 11110; Tag = "MIMAKI Ethernet (11110)" },
    @{ Port = 9100;  Tag = "MUTOH / Impresora RAW (9100)" },
    @{ Port = 11111; Tag = "MIMAKI Estado (11111)" }
)

$FoundPrinters = @()
foreach ($Prefix in $Subnets) {
    foreach ($PInfo in $ScanPorts) {
        $TargetPort = $PInfo.Port
        $Pending = @()
        for ($i = 1; $i -le 254; $i++) {
            $TestIp = "$Prefix.$i"
            $Client = New-Object System.Net.Sockets.TcpClient
            try {
                $Async = $Client.BeginConnect($TestIp, $TargetPort, $null, $null)
                $Pending += [PSCustomObject]@{ Ip = $TestIp; Client = $Client; Async = $Async }
            } catch {
                try { $Client.Close() } catch {}
            }
        }
        Start-Sleep -Milliseconds 650
        foreach ($Item in $Pending) {
            try {
                if ($Item.Async.IsCompleted -and $Item.Client.Connected) {
                    $FoundPrinters += [PSCustomObject]@{ Ip = $Item.Ip; Port = $TargetPort; Tag = $PInfo.Tag }
                    Log-Line ("  >>> ENCONTRADA: {0,-16} Puerto {1,-6} [{2}]" -f $Item.Ip, $TargetPort, $PInfo.Tag) "Green"
                }
            } catch {}
            try { $Item.Client.Close() } catch {}
        }
    }
}

if ($FoundPrinters.Count -eq 0) {
    Log-Line "  [AVISO] Ningun equipo respondio en puertos 9100 o 11110." "Yellow"
}
Log-Line ""

# 5. Leer tabla ARP completa del switch (incluye equipos que bloquean PING!)
Log-Line "[4/4] Equipos visibles en el Switch (tabla ARP - funciona aunque el PING este bloqueado):" "Cyan"
$ArpLines = arp -a
$DeviceCount = 0
foreach ($line in $ArpLines) {
    if ($line -match "^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s+(\S+)") {
        $aIp = $Matches[1]
        $aMac = $Matches[2].ToUpper()
        $aType = $Matches[3]
        if ($aIp -notlike "224.*" -and $aIp -notlike "239.*" -and $aIp -notlike "*.255" -and $aMac -ne "FF-FF-FF-FF-FF-FF") {
            $Note = ""
            if ($aIp -eq "192.168.1.240") { $Note = " <-- MUTOH VJ-1624" }
            elseif ($aIp -eq "192.168.1.73") { $Note = " <-- IP Mimaki probada" }
            $Color = if ($Note) { "Green" } else { "White" }
            Log-Line ("  IP: {0,-16}  MAC: {1,-19}  ({2}){3}" -f $aIp, $aMac, $aType, $Note) $Color
            $DeviceCount++
        }
    }
}
Log-Line "  Total dispositivos en switch: $DeviceCount" "Gray"
Log-Line ""
Log-Line "=====================================================================" "Cyan"
Log-Line "  Reporte guardado en: $ReportPath" "Yellow"
Log-Line "  Si ves una IP nueva en [ENCONTRADA] o en la tabla ARP, pasamela" "White"
Log-Line "  o pegame el contenido de este reporte para configurarla al instante." "White"
Log-Line "=====================================================================" "Cyan"

try { $Report | Out-File -FilePath $ReportPath -Encoding UTF8 } catch {}
