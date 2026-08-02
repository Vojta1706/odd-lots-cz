# nasadit.ps1 - jednorazove nasazeni projektu na GitHub
#
# Spusti se jednou. Udela vsechno, co je potreba, aby uloha bezela v cloudu:
#   1. zapise pripravene soubory
#   2. odesle je do repozitare Vojta1706/odd-lots-cz
#   3. ulozi oba API klice jako GitHub Secrets (cte je z Windows,
#      nikam se nevypisuji)
#   4. zapne GitHub Pages, kde pobezi RSS feed
#
# Pouziti:  pravy klik -> "Spustit pomoci PowerShellu"
#     nebo: powershell -File nasadit.ps1

# Chyby z externich programu (git, gh) resime rucne pres $LASTEXITCODE.
# "Stop" by tu skoncil i na necem, co je jen varovani na stderr.
$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$GH = "C:\Program Files\GitHub CLI\gh.exe"
$REPO = "Vojta1706/odd-lots-cz"
$TOKEN = "WDR45rRw0s_LBB0AhHyqovlB1dzcsoP4"

function Krok($cislo, $text) {
    Write-Host ""
    Write-Host "[$cislo/6] $text" -ForegroundColor Cyan
}

function Konec($kod) {
    Write-Host ""
    if (-not [Console]::IsInputRedirected) { Read-Host "Zavri stisknutim Enter" }
    exit $kod
}

try {
    if (-not (Test-Path $GH)) { throw "Nenasel jsem gh.exe. Je GitHub CLI nainstalovane?" }

    # --- 1. kontrola prihlaseni -------------------------------------------
    Krok 1 "Kontroluji prihlaseni na GitHub"
    & $GH auth status *> $null
    if ($LASTEXITCODE -ne 0) { throw "Nejsi prihlaseny. Spust nejdriv 'gh auth login'." }
    $kdo = (& $GH api user --jq .login)
    Write-Host "    prihlasen jako $kdo"

    # --- 2. zapis souboru --------------------------------------------------
    Krok 2 "Zapisuji pripravene soubory"
    & git config user.name "Vojta1706"
    & git config user.email "Vojta1706@users.noreply.github.com"
    & git add -A
    $jeCo = (& git diff --cached --name-only)
    if ($jeCo) {
        & git commit -q -m "Prevod podcastu Odd Lots do cestiny + rucni uloha pro GitHub Actions"
        Write-Host "    zapsano $($jeCo.Count) souboru"
    } else {
        Write-Host "    neni co zapisovat, pokracuji"
    }

    # --- 3. odeslani do repozitare ----------------------------------------
    Krok 3 "Odesilam do repozitare $REPO"
    $stavajici = @(& git remote 2>$null)
    if ($stavajici -contains "origin") {
        & git remote set-url origin "https://github.com/$REPO.git" | Out-Null
    } else {
        & git remote add origin "https://github.com/$REPO.git" | Out-Null
    }
    & git branch -M main | Out-Null
    & git push -u origin main
    if ($LASTEXITCODE -ne 0) { throw "Odeslani selhalo (kod $LASTEXITCODE)." }
    Write-Host "    hotovo"

    # --- 4. API klice jako Secrets ----------------------------------------
    Krok 4 "Ukladam API klice jako GitHub Secrets"
    foreach ($jmeno in @("ANTHROPIC_API_KEY", "GOOGLE_TTS_KEY")) {
        $hodnota = [Environment]::GetEnvironmentVariable($jmeno, "User")
        if (-not $hodnota) { throw "Ve Windows chybi promenna $jmeno." }
        $hodnota | & $GH secret set $jmeno --repo $REPO
        if ($LASTEXITCODE -ne 0) { throw "Ulozeni klice $jmeno selhalo." }
        Write-Host "    $jmeno ulozen (delka $($hodnota.Length) znaku)"
    }

    # --- 5. zapnuti GitHub Pages ------------------------------------------
    Krok 5 "Zapinam GitHub Pages"
    $telo = '{"source":{"branch":"main","path":"/docs"}}'
    $telo | & $GH api "repos/$REPO/pages" -X POST --input - 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # uz zapnute -> jen prenastavime zdroj
        $telo | & $GH api "repos/$REPO/pages" -X PUT --input - 2>$null | Out-Null
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "    zapnuto (rozjezd trva par minut)"
    } else {
        Write-Host "    nepovedlo se automaticky - zapni rucne:" -ForegroundColor Yellow
        Write-Host "    Settings -> Pages -> Source: Deploy from a branch -> main / docs" -ForegroundColor Yellow
    }

    # --- 6. shrnuti --------------------------------------------------------
    Krok 6 "Hotovo"
    Write-Host ""
    Write-Host "  Repozitar:  https://github.com/$REPO" -ForegroundColor Green
    Write-Host "  Spousteni:  https://github.com/$REPO/actions" -ForegroundColor Green
    Write-Host "  Adresa feedu (do podcastove aplikace):" -ForegroundColor Green
    Write-Host "  https://vojta1706.github.io/odd-lots-cz/$TOKEN/feed.xml" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Feed zacne fungovat, az probehne prvni epizoda."
    Konec 0
}
catch {
    Write-Host ""
    Write-Host "CHYBA: $($_.Exception.Message)" -ForegroundColor Red
    Konec 1
}
