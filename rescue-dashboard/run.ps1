<#
  Start the whole control room with ONE command, and keep it up to date while you code.

    .\run.ps1              backend + dashboard + responder site on http://localhost:8001
    .\run.ps1 -Tunnel      also open a Cloudflare tunnel for the phones (address shown in its own window)
    .\run.ps1 -Port 8002   use another port
    .\run.ps1 -NoWatch     build once and run, without auto-rebuild/auto-restart

  While it runs:
    * save a .py file in backend\        -> the server restarts by itself (a few seconds)
    * save a file in frontend\ or responder\ -> that site rebuilds by itself; refresh the browser
    * Python / npm packages are installed again only when requirements.txt / package-lock.json change

  Press Ctrl+C to stop everything.
  If Windows blocks the script, double-click run.bat instead (or run:
  powershell -ExecutionPolicy Bypass -File .\run.ps1).
#>
param(
    [int]$Port = 8001,
    [switch]$Tunnel,
    [switch]$NoWatch,
    [switch]$NoChatbot
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Venv = Join-Path $Backend '.venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$started = @()

function Say($text, $color = 'Cyan') { Write-Host "[run] $text" -ForegroundColor $color }

function FileHash($path) {
    if (Test-Path $path) { (Get-FileHash $path -Algorithm SHA256).Hash } else { '' }
}

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Say "$cmd is not installed. $hint" 'Red'
        exit 1
    }
}

# ------------------------------------------------------------------ checks
Need 'python' 'Install Python 3.10+ from python.org (tick "Add to PATH").'
Need 'npm' 'Install Node.js 18+ from nodejs.org.'

# ------------------------------------------------------------------ backend packages
if (-not (Test-Path $Py)) {
    Say 'Creating the Python environment (first run only)...'
    python -m venv $Venv
}
$reqFile = Join-Path $Backend 'requirements.txt'
$reqStamp = Join-Path $Venv '.requirements.sha256'
$reqHash = FileHash $reqFile
if ((-not (Test-Path $reqStamp)) -or ((Get-Content $reqStamp -Raw).Trim() -ne $reqHash)) {
    Say 'Installing backend packages (requirements.txt changed)...'
    & $Py -m pip install --disable-pip-version-check -q -r $reqFile
    if ($LASTEXITCODE -ne 0) { Say 'pip install failed (see above).' 'Red'; exit 1 }
    Set-Content -Path $reqStamp -Value $reqHash -Encoding ascii
}

if (-not (Test-Path (Join-Path $Backend '.env'))) {
    Say 'backend\.env not found: AI features (triage, voice, photo checks) will use the fallback rules.' 'Yellow'
    Say 'Create backend\.env with a line  GROQ_API_KEY=...  to turn them on.' 'Yellow'
}

# ------------------------------------------------------------------ website packages + first build
foreach ($site in 'frontend', 'responder') {
    $dir = Join-Path $Root $site
    $lock = Join-Path $dir 'package-lock.json'
    $stamp = Join-Path $dir 'node_modules\.lock.sha256'
    $lockHash = FileHash $lock
    if ((-not (Test-Path (Join-Path $dir 'node_modules'))) -or (-not (Test-Path $stamp)) -or
        ((Get-Content $stamp -Raw).Trim() -ne $lockHash)) {
        Say "Installing $site packages (package-lock.json changed)..."
        Push-Location $dir
        try { npm install --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { throw "npm install failed in $site" } }
        finally { Pop-Location }
        Set-Content -Path $stamp -Value $lockHash -Encoding ascii
    }
    # Build once now so the server always has a current site, even before the watcher finishes.
    Say "Building $site..."
    Push-Location $dir
    try { npm run build --silent; if ($LASTEXITCODE -ne 0) { throw "build failed in $site (fix the error above and run again)" } }
    finally { Pop-Location }
}

# ------------------------------------------------------------------ free the port
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($busy) {
    $p = Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -match '^(python|uvicorn)') {
        Say "Stopping the old server on port $Port (pid $($p.Id))..." 'Yellow'
        & taskkill /PID $p.Id /T /F | Out-Null
        Start-Sleep -Seconds 1
    } else {
        Say "Port $Port is used by '$($p.ProcessName)'. Close it or run: .\run.ps1 -Port 8002" 'Red'
        exit 1
    }
}

# ------------------------------------------------------------------ run
try {
    if (-not $NoWatch) {
        # Watchers left over from a run whose window was closed with X (Ctrl+C cleans up itself)
        Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine.Contains($Root) -and $_.CommandLine -match 'vite' -and $_.CommandLine -match '--watch' } |
            ForEach-Object { Say "Stopping an old site watcher (pid $($_.ProcessId))." 'Yellow'; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        foreach ($site in 'frontend', 'responder') {
            # vite build --watch: rebuilds dist\ whenever a source file changes (minimised window)
            $w = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'build', '--', '--watch' `
                -WorkingDirectory (Join-Path $Root $site) -WindowStyle Minimized -PassThru
            $started += $w
            Say "Watching $site for changes (pid $($w.Id), minimised window)."
        }
    }

    # AI chatbot server for the mesh app (ai-surveillance\disaster_api_server.py on port 8800).
    # The app reaches it through this backend (/api/chat), over the same https tunnel as Sync.
    if (-not $NoChatbot) {
        $ai = Join-Path (Split-Path $Root -Parent) 'ai-surveillance'
        $aiPy = Join-Path $ai '.venv\Scripts\python.exe'
        if (-not (Test-Path $aiPy)) { $aiPy = 'python' }
        if (Test-Path (Join-Path $ai 'disaster_api_server.py')) {
            $old = Get-NetTCPConnection -LocalPort 8800 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($old) {
                $op = Get-Process -Id $old.OwningProcess -ErrorAction SilentlyContinue
                if ($op -and $op.ProcessName -match '^python') { & taskkill /PID $op.Id /T /F | Out-Null; Start-Sleep -Seconds 1 }
            }
            $cb = Start-Process -FilePath $aiPy -ArgumentList 'disaster_api_server.py', '--port', '8800' `
                -WorkingDirectory $ai -WindowStyle Minimized -PassThru
            $started += $cb
            Say "AI chatbot server started on port 8800 (pid $($cb.Id), minimised window)."
        } else {
            Say 'ai-surveillance\disaster_api_server.py not found: the app chatbot will say it is unavailable.' 'Yellow'
        }
    }

    if ($Tunnel) {
        $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
        if (-not $cf -and (Test-Path (Join-Path $Root 'cloudflared.exe'))) { $cf = Join-Path $Root 'cloudflared.exe' }
        if ($cf) {
            $t = Start-Process -FilePath $cf -ArgumentList 'tunnel', '--url', "http://localhost:$Port" -PassThru
            $started += $t
            Say 'Tunnel window opened: copy the https://....trycloudflare.com address from it (select + right-click, not Ctrl+C).'
            Say 'Phones: Sync URL = that address + /api/v1/bitchat/civ-sync'
        } else {
            Say 'cloudflared not found: run  winget install --id Cloudflare.cloudflared  then open a NEW window.' 'Yellow'
        }
    }

    $env:PYTHONUTF8 = '1'
    $graph = Join-Path $Backend 'roads_dehradun.graphml'
    if (Test-Path $graph) { $env:ROAD_GRAPH = 'roads_dehradun.graphml' }

    Write-Host ''
    Say "Dashboard:       http://localhost:$Port" 'Green'
    Say "Responder site:  http://localhost:$Port/responder/" 'Green'
    Say "API docs:        http://localhost:$Port/docs" 'Green'
    Say 'Press Ctrl+C to stop everything.' 'Green'
    Write-Host ''

    $uv = @('-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', "$Port")
    if (-not $NoWatch) {
        # restart on .py changes in backend\ only (not the database, media, venv or node_modules)
        $uv += @('--reload', '--reload-dir', '.', '--reload-exclude', '.venv', '--reload-exclude', 'media',
                 '--reload-exclude', '__pycache__')
    }
    Push-Location $Backend
    try { & $Py @uv }
    finally { Pop-Location }
}
finally {
    $ErrorActionPreference = 'Continue'   # never fail while cleaning up
    foreach ($p in $started) {
        try { if ($p -and -not $p.HasExited) { & taskkill /PID $p.Id /T /F | Out-Null } } catch { }
    }
    Say 'Stopped.' 'Yellow'
}
