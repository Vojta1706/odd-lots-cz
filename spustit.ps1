# Spousteci skript pro podcast_cz.py
#
# Pouziti:
#   pravy klik na soubor -> "Spustit pomoci PowerShellu"   (zepta se na URL)
#
#   nebo v terminalu:
#     .\spustit.ps1                                   ukazka, zepta se na URL
#     .\spustit.ps1 "https://omny.fm/shows/..."       ukazka z dane epizody
#     .\spustit.ps1 "https://omny.fm/shows/..." -Full  cela epizoda

param(
    [Parameter(Position = 0)]
    [string]$Url,
    [switch]$Full
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# Ptat se muzeme jen tehdy, kdyz opravdu sedi clovek u klavesnice.
# Pri automatickem spusteni je vstup presmerovany a Read-Host by se zasekl.
$Interaktivni = -not [Console]::IsInputRedirected

function Konec($kod) {
    if ($Interaktivni) {
        Write-Host ""
        Read-Host "Zavri stisknutim Enter"
    }
    exit $kod
}

try {
    # --- cesty k nastrojum (winget je nedava do PATH hned) ---
    $python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $python)) {
        $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    }
    if (-not $python) { throw "Nenasel jsem Python." }

    $ffmpegBin = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin"
    if (Test-Path $ffmpegBin) { $env:PATH = "$ffmpegBin;$env:PATH" }

    # --- klice ctene primo z uzivatelskeho nastaveni Windows ---
    if (-not $env:ANTHROPIC_API_KEY) {
        $env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
    }
    if (-not $env:GOOGLE_TTS_KEY) {
        $env:GOOGLE_TTS_KEY = [Environment]::GetEnvironmentVariable("GOOGLE_TTS_KEY", "User")
    }
    if (-not $env:ANTHROPIC_API_KEY) { throw "Chybi ANTHROPIC_API_KEY. Nastav ho podle navodu." }
    if (-not $env:GOOGLE_TTS_KEY)    { throw "Chybi GOOGLE_TTS_KEY. Nastav ho podle navodu." }

    # --- cestina ve vypisu ---
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    # --- URL epizody ---
    if (-not $Url) {
        if (-not $Interaktivni) {
            throw "Nezadal jsi URL epizody. Spust: .\spustit.ps1 ""https://omny.fm/shows/..."""
        }
        Write-Host ""
        Write-Host "Vloz adresu epizody z omny.fm."
        Write-Host "Napriklad: https://omny.fm/shows/odd-lots/nazev-epizody"
        Write-Host ""
        $Url = Read-Host "URL epizody"
    }
    $Url = $Url.Trim().Trim('"').Trim("'")
    if (-not $Url) { throw "Zadna adresa nezadana." }
    if ($Url -notmatch '^https?://') { throw "'$Url' nevypada jako adresa. Musi zacinat https://" }
    if ($Url -notmatch 'omny\.fm') {
        Write-Host "Pozor: adresa neni z omny.fm, skript si s ni nemusi poradit." -ForegroundColor Yellow
    }

    # --- rezim ---
    if (-not $Full -and -not $PSBoundParameters.ContainsKey('Full') -and $Interaktivni) {
        Write-Host ""
        $odp = Read-Host "Zpracovat celou epizodu? (a = ano, cokoliv jineho = jen ukazka)"
        if ($odp -match '^\s*[aAyY]') { $Full = $true }
    }

    # --- nazev vystupu podle epizody, at se runy neprepisuji ---
    $slug = ($Url.TrimEnd('/') -split '/')[-1] -replace '\?.*$', ''
    if (-not $slug) { $slug = "epizoda" }
    $slug = $slug -replace '[^a-zA-Z0-9\-_]', ''
    if ($slug.Length -gt 60) { $slug = $slug.Substring(0, 60) }
    $vystup = if ($Full) { "$slug`_cz.mp3" } else { "$slug`_ukazka.mp3" }

    $argy = @($Url, "--vystup", $vystup)
    if ($Full) { $argy += "--full" }

    Write-Host ""
    Write-Host ("Rezim:  " + $(if ($Full) { "CELA EPIZODA" } else { "ukazka (prvnich 15 replik)" }))
    Write-Host "Vystup: $vystup"
    Write-Host ""

    & $python "podcast_cz.py" @argy
    if ($LASTEXITCODE -ne 0) { throw "Skript skoncil s chybou (kod $LASTEXITCODE)." }

    Write-Host ""
    Write-Host "Hotovo: $vystup" -ForegroundColor Green
    Konec 0
}
catch {
    Write-Host ""
    Write-Host "CHYBA: $($_.Exception.Message)" -ForegroundColor Red
    Konec 1
}
