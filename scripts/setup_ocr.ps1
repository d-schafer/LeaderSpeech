# setup_ocr.ps1 - make PDF OCR work on THIS machine for the LeaderSpeech scraper.
#
# Idempotent: safe to re-run; it only does what is missing. Walkthrough: docs/ocr_setup.md.
# Keep this file ASCII-only (Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI).
#
# WHAT IT DOES
#   1. pip install -e "<repo>[pdf,pdf-ocr]" into the leaderspeech_scrape venv (ocrmypdf).
#   2. Tesseract 5.5+: keeps a good install; otherwise installs the OFFICIAL winget package
#      tesseract-ocr.tesseract (one UAC prompt). NOT UB-Mannheim.TesseractOCR: that package is
#      5.4.0, which ocrmypdf refuses outright ("regressions in this version").
#   3. Puts Tesseract's folder on your USER PATH if it is on no PATH yet.
#   4. Downloads tessdata_best language packs into a PER-USER folder (no admin needed):
#      %LOCALAPPDATA%\leaderspeech\tessdata - by default every language a recipe uses (the list
#      comes from `python -m leaderspeech.text_scraper.ocr_check --needed`), plus eng + osd.
#      Copies Tesseract's own configs/, tessconfigs/, pdf.ttf and any packs already installed
#      there, so nothing that worked before stops working.
#   5. Sets the USER environment variable TESSDATA_PREFIX to that folder. (Tesseract 5 reads it
#      as the tessdata folder itself.) New PowerShell windows pick it up; this one is updated too.
#   6. Ghostscript is NOT needed (the engine never asks ocrmypdf for PDF/A). -Ghostscript installs
#      it anyway.
#   7. Runs the doctor: python -m leaderspeech.text_scraper.ocr_check (with a real OCR smoke test).
#
# HOW TO RUN (from the LeaderSpeech workspace root or anywhere):
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#     & ".\github_repo\LeaderSpeech\scripts\setup_ocr.ps1"
#   From a COMMAND PROMPT:
#     powershell -NoProfile -ExecutionPolicy Bypass -File .\github_repo\LeaderSpeech\scripts\setup_ocr.ps1
#
# SWITCHES
#   -PdfOnly        only the languages of recipes that read PDFs (smaller download)
#   -All            every tessdata pack there is (~130 languages; large)
#   -Fast           tessdata_fast instead of tessdata_best (smaller, less accurate on old scans)
#   -Force          re-download packs that are already present
#   -Ghostscript    also install Ghostscript (optional)
#   -SkipPip        don't touch the venv
#   -SkipTesseract  don't install/upgrade Tesseract (report only)
#   -Python <path>  the venv python.exe, if it is not in one of the usual places
#   -TessdataDir <path>   where the packs go (default %LOCALAPPDATA%\leaderspeech\tessdata)

[CmdletBinding()]
param(
    [switch]$PdfOnly,
    [switch]$All,
    [switch]$Fast,
    [switch]$Force,
    [switch]$Ghostscript,
    [switch]$SkipPip,
    [switch]$SkipTesseract,
    [string]$Python = "",
    [string]$TessdataDir = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # PS 5.1's progress bar slows downloads ~10x
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Say([string]$msg, [string]$color = "Gray") { Write-Host $msg -ForegroundColor $color }
function Step([string]$msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }

$repo = Split-Path $PSScriptRoot -Parent
if (-not $TessdataDir) { $TessdataDir = Join-Path $env:LOCALAPPDATA "leaderspeech\tessdata" }
$flavor = if ($Fast) { "tessdata_fast" } else { "tessdata_best" }

# --- 0. the venv python ---------------------------------------------------------------------
Step "Python (leaderspeech_scrape venv)"
$pyCandidates = @(@(
    $Python,
    $env:LEADERSPEECH_PY,
    "D:\environments\leaderspeech_scrape\Scripts\python.exe",
    "C:\Projects\environments\leaderspeech_scrape\Scripts\python.exe",
    "C:\environments\leaderspeech_scrape\Scripts\python.exe"
) | Where-Object { $_ -and (Test-Path $_) })
if ($pyCandidates.Count -eq 0) {
    Say "!! Could not find the leaderspeech_scrape python.exe. Re-run with -Python <path>." Red
    exit 1
}
$py = $pyCandidates[0]
Say "python : $py"
Say "repo   : $repo"

# --- 1. ocrmypdf in the venv ----------------------------------------------------------------
if (-not $SkipPip) {
    Step "pip install -e `"$repo[pdf,pdf-ocr]`""
    & $py -m pip install --disable-pip-version-check -q -e ($repo + "[pdf,pdf-ocr]")
    if ($LASTEXITCODE -ne 0) { Say "!! pip install failed (see above)." Red; exit 1 }
    Say "ok" Green
}

# --- 2. Tesseract ---------------------------------------------------------------------------
function Find-Tesseract {
    $cmd = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)},
                        (Join-Path $env:LOCALAPPDATA "Programs"))) {
        if (-not $base) { continue }
        $p = Join-Path $base "Tesseract-OCR\tesseract.exe"
        if (Test-Path $p) { return $p }
    }
    return $null
}
function Get-TesseractVersion([string]$exe) {
    $out = (& $exe --version 2>&1 | Out-String)
    if ($out -match "tesseract\s+v?(\d+\.\d+\.\d+)") { return [version]$Matches[1] }
    return $null
}

Step "Tesseract"
$tess = Find-Tesseract
$ver = if ($tess) { Get-TesseractVersion $tess } else { $null }
if ($tess) { Say "found  : $tess  (version $ver)" } else { Say "found  : none" Yellow }
$needInstall = (-not $tess) -or (-not $ver) -or ($ver -lt [version]"5.5.0")
if ($needInstall -and $SkipTesseract) {
    Say "!! Tesseract missing or older than 5.5 (5.4.0 is refused by ocrmypdf) - skipped (-SkipTesseract)." Yellow
} elseif ($needInstall) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Say "!! winget is not available. Install Tesseract 5.5+ by hand from" Red
        Say "   https://github.com/tesseract-ocr/tesseract/releases (tesseract-ocr-w64-setup-5.5.x.exe)" Red
        exit 1
    }
    if ($ver -and $ver -eq [version]"5.4.0") {
        Say "Tesseract 5.4.0 (UB-Mannheim) is installed and ocrmypdf refuses it - removing it first." Yellow
        winget uninstall -e --id UB-Mannheim.TesseractOCR --silent 2>&1 | Out-Host
    }
    Say "installing tesseract-ocr.tesseract via winget (approve the UAC prompt) ..." Yellow
    winget install -e --id tesseract-ocr.tesseract --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Host
    $tess = Find-Tesseract
    if (-not $tess) {
        Say "!! Tesseract still not found. If the installer asked for administrator rights and was" Red
        Say "   declined, run this script again from an elevated PowerShell (Run as administrator)." Red
        exit 1
    }
    $ver = Get-TesseractVersion $tess
    Say "now    : $tess  (version $ver)" Green
}

# --- 3. PATH --------------------------------------------------------------------------------
if ($tess) {
    $tessDir = Split-Path $tess -Parent
    $onPath = (($env:Path -split ";") | Where-Object { $_.TrimEnd("\") -ieq $tessDir.TrimEnd("\") })
    if (-not $onPath) {
        Step "PATH"
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        $newUser = if ($userPath) { "$userPath;$tessDir" } else { $tessDir }
        [Environment]::SetEnvironmentVariable("Path", $newUser, "User")
        $env:Path = "$env:Path;$tessDir"
        Say "added $tessDir to your USER PATH" Green
    }
}

# --- 4. language packs ----------------------------------------------------------------------
Step "Language packs ($flavor) -> $TessdataDir"
New-Item -ItemType Directory -Force -Path $TessdataDir | Out-Null

if ($All) {
    $tree = Invoke-RestMethod -UseBasicParsing "https://api.github.com/repos/tesseract-ocr/$flavor/git/trees/main"
    $codes = @($tree.tree | Where-Object { $_.path -like "*.traineddata" -and $_.path -notlike "*/*" } |
               ForEach-Object { $_.path -replace "\.traineddata$", "" })
} else {
    $neededArgs = @("-m", "leaderspeech.text_scraper.ocr_check", "--needed")
    if ($PdfOnly) { $neededArgs += "--documents-only" }
    $codes = @((& $py @neededArgs | Out-String).Trim() -split "\s+" | Where-Object { $_ })
}
$codes = @(@($codes) + @("eng", "osd") | Sort-Object -Unique)
Say ("{0} pack(s): {1}" -f $codes.Count, ($codes -join " "))

# carry over what Tesseract's own tessdata already has (configs are REQUIRED: ocrmypdf asks
# Tesseract for its hocr/txt/pdf output configs, which Tesseract looks up in TESSDATA_PREFIX)
if ($tess) {
    $ownData = Join-Path (Split-Path $tess -Parent) "tessdata"
    if (Test-Path $ownData) {
        foreach ($item in @("configs", "tessconfigs", "pdf.ttf")) {
            $src = Join-Path $ownData $item
            if (Test-Path $src) { Copy-Item $src -Destination $TessdataDir -Recurse -Force }
        }
        Get-ChildItem $ownData -Filter *.traineddata | ForEach-Object {
            $dst = Join-Path $TessdataDir $_.Name
            if (-not (Test-Path $dst)) { Copy-Item $_.FullName $dst }
        }
    }
}

$got = 0; $kept = 0; $failed = @()
foreach ($code in $codes) {
    $dst = Join-Path $TessdataDir "$code.traineddata"
    $marker = Join-Path $TessdataDir ".$code.$flavor"     # records that THIS flavor was fetched
    if ((Test-Path $dst) -and (Test-Path $marker) -and -not $Force) { $kept++; continue }
    $url = "https://github.com/tesseract-ocr/$flavor/raw/main/$code.traineddata"
    $part = "$dst.part"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $part
        if ((Get-Item $part).Length -lt 10000) { throw "suspiciously small download" }
        Move-Item $part $dst -Force
        Set-Content -Path $marker -Value (Get-Date -Format s) -Encoding ASCII
        $got++
        Say ("  + {0,-10} {1,6:N1} MB" -f $code, ((Get-Item $dst).Length / 1MB))
    } catch {
        if (Test-Path $part) { Remove-Item $part -Force }
        $failed += $code
        Say "  !! $code : $($_.Exception.Message)" Red
    }
}
Say ("downloaded {0}, already present {1}, failed {2}" -f $got, $kept, $failed.Count)

# --- 5. TESSDATA_PREFIX ---------------------------------------------------------------------
Step "TESSDATA_PREFIX"
$current = [Environment]::GetEnvironmentVariable("TESSDATA_PREFIX", "User")
if ($current -ne $TessdataDir) {
    [Environment]::SetEnvironmentVariable("TESSDATA_PREFIX", $TessdataDir, "User")
    Say "set USER TESSDATA_PREFIX = $TessdataDir  (was: $current)" Green
} else {
    Say "already $TessdataDir"
}
$env:TESSDATA_PREFIX = $TessdataDir
$machineVal = [Environment]::GetEnvironmentVariable("TESSDATA_PREFIX", "Machine")
if ($machineVal -and $machineVal -ne $TessdataDir) {
    Say "note: a MACHINE-level TESSDATA_PREFIX ($machineVal) also exists; the USER value wins for you." Yellow
}

# --- 6. Ghostscript (optional) --------------------------------------------------------------
if ($Ghostscript) {
    Step "Ghostscript (optional)"
    $gs = Get-Command gswin64c -ErrorAction SilentlyContinue
    if ($gs) {
        Say "found: $($gs.Source)"
    } else {
        $rel = Invoke-RestMethod -UseBasicParsing "https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases/latest"
        $asset = $rel.assets | Where-Object { $_.name -match "^gs\d+w64\.exe$" } | Select-Object -First 1
        if (-not $asset) { Say "!! no 64-bit Windows installer in the latest release" Red }
        else {
            $exe = Join-Path $env:TEMP $asset.name
            Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile $exe
            Say "running $($asset.name) /S (approve the UAC prompt) ..." Yellow
            Start-Process -FilePath $exe -ArgumentList "/S" -Verb RunAs -Wait
        }
    }
}

# --- 7. the doctor --------------------------------------------------------------------------
Step "Check (python -m leaderspeech.text_scraper.ocr_check)"
$checkArgs = @("-m", "leaderspeech.text_scraper.ocr_check", "--smoke-lang", "spa")
if ($PdfOnly) { $checkArgs += "--documents-only" }
& $py @checkArgs
$code = $LASTEXITCODE
Write-Host ""
if ($code -eq 0) {
    Say "OCR is ready on this machine. Open a NEW PowerShell window before running a queue" Green
    Say "(so it inherits TESSDATA_PREFIX and PATH)." Green
} elseif ($code -eq 2) {
    Say "OCR works, but some packs are missing (see above). Re-run this script to retry them." Yellow
} else {
    Say "OCR is NOT working yet - see the problems above and docs/ocr_setup.md." Red
}
exit $code
