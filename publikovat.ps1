# publikovat.ps1 - posle zmeny feedu (obal, nastaveni, kod) na GitHub
#
# Pouzij pokazde, kdyz zmenis obal nebo nazev podcastu.
# Bezne epizody tohle nepotrebuji - ty si feed aktualizuji samy pri behu ulohy.
#
# Poradi kroku je dulezite: nejdriv zapsat mistni zmeny, pak stahnout z GitHubu
# (odkud prijde seznam uz hotovych epizod) a teprve potom prepocitat feed.
# Kdyby se feed pocital pred stazenim, prepsal by se prazdnym a epizody by zmizely.
#
# Pouziti:  pravy klik -> "Spustit pomoci PowerShellu"
#     nebo: powershell -File publikovat.ps1

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$PY = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$TOKEN = "WDR45rRw0s_LBB0AhHyqovlB1dzcsoP4"

function Krok($c, $t) { Write-Host ""; Write-Host "[$c/5] $t" -ForegroundColor Cyan }
function Konec($kod) {
    Write-Host ""
    if (-not [Console]::IsInputRedirected) { Read-Host "Zavri stisknutim Enter" }
    exit $kod
}

try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    Krok 1 "Zapisuji mistni zmeny"
    & git add -A
    $zmeny = @(& git diff --cached --name-only)
    if ($zmeny.Count -gt 0) {
        foreach ($z in $zmeny) { Write-Host "    $z" }
        & git commit -q -m "Feed: obal a nastaveni"
        if ($LASTEXITCODE -ne 0) { throw "Zapis zmen selhal." }
    } else {
        Write-Host "    nic noveho"
    }

    Krok 2 "Stahuji stav z GitHubu"
    & git pull --rebase
    if ($LASTEXITCODE -ne 0) {
        throw "Stazeni selhalo. Zkus to znovu, nebo mi posli, co se vypsalo."
    }
    Write-Host "    hotovo"

    Krok 3 "Prepocitavam feed"
    & $PY cloud/feed.py --pregeneruj
    if ($LASTEXITCODE -ne 0) { throw "Prepocet feedu selhal." }

    Krok 4 "Zapisuji prepocitany feed"
    & git add -A
    $zmeny2 = @(& git diff --cached --name-only)
    if ($zmeny2.Count -gt 0) {
        & git commit -q -m "Feed: prepocet"
    } else {
        Write-Host "    feed se nezmenil"
    }

    Krok 5 "Odesilam na GitHub"
    $napred = @(& git log "origin/main..HEAD" --oneline)
    if ($napred.Count -eq 0) {
        Write-Host "    neni co odesilat"
    } else {
        & git push
        if ($LASTEXITCODE -ne 0) { throw "Odeslani selhalo." }
        Write-Host "    odeslano $($napred.Count) zmen"
    }

    Write-Host ""
    Write-Host "  Hotovo. Feed se aktualizuje do minuty." -ForegroundColor Green
    Write-Host "  https://vojta1706.github.io/odd-lots-cz/$TOKEN/feed.xml" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Podcastove aplikace si obrazky drzi v pameti, takze obal se"
    Write-Host "  nemusi prekreslit hned. Nejrychleji pomuze feed odebrat a pridat znovu."
    Konec 0
}
catch {
    Write-Host ""
    Write-Host "CHYBA: $($_.Exception.Message)" -ForegroundColor Red
    Konec 1
}
