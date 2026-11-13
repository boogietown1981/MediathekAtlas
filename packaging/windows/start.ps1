# MediathekAtlas @VERSION@ – Windows launcher (started hidden from the Start menu shortcut).
# Finds Python 3.9+, copies the program into a stable runtime folder (so an update can replace
# the installation while the app runs) and starts the local server; the browser opens by itself.
param([switch]$Diagnose)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$App = Split-Path -Parent $MyInvocation.MyCommand.Path
$State = if ($env:MEDIATHEKATLAS_HOME) { $env:MEDIATHEKATLAS_HOME } else { Join-Path $env:LOCALAPPDATA 'MediathekAtlas' }
New-Item -ItemType Directory -Force -Path $State | Out-Null
$Log = Join-Path $State 'startup.log'
"MediathekAtlas @VERSION@ Startprüfung (Windows)" | Set-Content -Encoding UTF8 $Log
function Say($text) { $text | Add-Content -Encoding UTF8 $Log }
function Fail($text) {
  Say $text
  $answer = [System.Windows.Forms.MessageBox]::Show("$text`n`nStartprotokoll öffnen?", 'MediathekAtlas', 'YesNo', 'Error')
  if ($answer -eq 'Yes') { Start-Process notepad.exe $Log }
  exit 1
}
function Test-Python($exe, $prefix) {
  try {
    $pyArgs = @($prefix) + @('-c', 'import sys, sqlite3, ssl, urllib.request; print(sys.executable); sys.exit(0 if sys.version_info >= (3,9) else 1)') | Where-Object { $_ }
    $out = & $exe @pyArgs 2>> $Log
    if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -Last 1).Trim() }
  } catch { }
  return $null
}
$python = $null
$candidates = @()
if ($env:MEDIATHEKATLAS_PYTHON) { $candidates += ,@($env:MEDIATHEKATLAS_PYTHON, $null) }
$candidates += ,@('py', '-3')
$candidates += ,@('python', $null)
foreach ($dir in Get-ChildItem -Directory -ErrorAction SilentlyContinue "$env:LOCALAPPDATA\Programs\Python\Python3*", "$env:ProgramFiles\Python3*") {
  $candidates += ,@((Join-Path $dir.FullName 'python.exe'), $null)
}
foreach ($c in $candidates) {
  $found = Test-Python $c[0] $c[1]
  if ($found -and (Test-Path $found)) { $python = $found; break }
}
if (-not $python) {
  Say 'Kein Python ab 3.9 gefunden.'
  $msg = "MediathekAtlas braucht Python 3.9 oder neuer.`n`nJetzt Python über winget installieren? (Nein öffnet python.org)"
  $answer = [System.Windows.Forms.MessageBox]::Show($msg, 'MediathekAtlas', 'YesNoCancel', 'Warning')
  if ($answer -eq 'Yes' -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    Start-Process winget -ArgumentList 'install','-e','--id','Python.Python.3.12','--scope','user','--accept-package-agreements','--accept-source-agreements' -Wait
    [System.Windows.Forms.MessageBox]::Show('Python wurde installiert. Bitte MediathekAtlas erneut starten.', 'MediathekAtlas') | Out-Null
  } elseif ($answer -ne 'Cancel') { Start-Process 'https://www.python.org/downloads/windows/' }
  exit 1
}
Say "Ausgewähltes Python: $python"
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $python }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Say 'Hinweis: ffmpeg fehlt – für Downloads empfohlen (winget install Gyan.FFmpeg).' }
$runtime = & $python (Join-Path $App 'app\stable_runtime.py') (Join-Path $App 'app') $State 2>> $Log
if ($LASTEXITCODE -ne 0 -or -not $runtime) { Fail 'Programmdateien konnten nicht vorbereitet werden.' }
$runtime = ($runtime | Select-Object -Last 1).Trim()
$env:MEDIATHEKATLAS_HOME = $State
$env:PYTHONIOENCODING = 'utf-8'
if ($Diagnose) {
  $zip = & $python (Join-Path $runtime 'diagnostics_cli.py') 2>> $Log
  if ($zip) { Start-Process explorer.exe "/select,`"$(($zip | Select-Object -Last 1).Trim())`"" }
  exit 0
}
$proc = Start-Process -FilePath $pythonw -ArgumentList 'server.py' -WorkingDirectory $runtime -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $State 'server.out.log') -RedirectStandardError (Join-Path $State 'server.err.log')
Start-Sleep -Seconds 4
if ($proc.HasExited -and $proc.ExitCode -ne 0) {
  Get-Content (Join-Path $State 'server.err.log') -ErrorAction SilentlyContinue | Add-Content -Encoding UTF8 $Log
  Fail 'MediathekAtlas konnte nicht gestartet werden. Details stehen im Startprotokoll.'
}
