#!/usr/bin/env python3
"""
podcast_cz.py - z anglickeho podcastu vyrobi ceskou zvukovou epizodu.

CO TO DELA
    1. Ziska transkript - bud z URL epizody na omny.fm, nebo z textoveho souboru
    2. Rozdeli ho na repliky podle mluvcich
    3. Prelozi je pres Claude API do cestiny (s ohledem na kontext a zargon)
    4. Kazdemu mluvcimu prideli jiny cesky hlas (Google Cloud TTS)
    5. Slepi vsechno pomoci ffmpeg do jednoho MP3

CO POTREBUJES NAINSTALOVAT
    - Python 3.9+          https://www.python.org/downloads/
    - ffmpeg               https://ffmpeg.org/download.html
    - knihovnu requests:   pip install requests

DVA API KLICE
    ANTHROPIC_API_KEY  - console.anthropic.com -> Settings -> API Keys
                         (je potreba dobit kredit, par dolaru bohate staci)
    GOOGLE_TTS_KEY     - console.cloud.google.com -> zaloz projekt
                         -> zapni "Cloud Text-to-Speech API"
                         -> APIs & Services -> Credentials -> Create API key
                         POZOR: hned si tam nastav rozpoctove upozorneni.

    Klice se predavaji jako promenne prostredi:

        macOS / Linux:
            export ANTHROPIC_API_KEY="sk-ant-..."
            export GOOGLE_TTS_KEY="AIza..."

        Windows (PowerShell):
            $env:ANTHROPIC_API_KEY="sk-ant-..."
            $env:GOOGLE_TTS_KEY="AIza..."

JAK TO SPUSTIT
    # 1. nejdriv kratka ukazka - prvnich 15 replik, hotovo za minutu
    python podcast_cz.py https://omny.fm/shows/odd-lots/nazev-epizody

    # 2. az budes spokojeny, cela epizoda
    python podcast_cz.py https://omny.fm/shows/odd-lots/nazev-epizody --full

    # porad funguje i rucne zkopirovany prepis ze souboru
    python podcast_cz.py prepis.txt

    # vypis dostupnych ceskych hlasu (kdyz chces zmenit obsazeni)
    python podcast_cz.py --hlasy

ODKUD SE BERE PREPIS
    Stranka epizody na omny.fm ma primo v HTML pole "TranscriptUrl", ktere
    ukazuje na api.omny.fm/orgs/<org>/clips/<clip>/transcript. To vraci JSON
    s rozpoznanymi mluvcimi a casovanim jednotlivych slov - presne to, co
    potrebujeme. Zadny JavaScript se kvuli tomu spoustet nemusi.

    Kdyz epizoda publikovany prepis nema, skript spadne na zalozni cestu:
    stahne MP3 (pole "AudioUrl" na stejne strance) a necha ho prepsat pres
    Google Speech-to-Text se zapnutym rozpoznavanim mluvcich. To je pomalejsi
    a placene - u hodinove epizody pocitej s ~15 minutami a ~1,5 dolaru.

    POZOR: zalozni cesta potrebuje v Google Cloud navic zapnout
    "Cloud Speech-to-Text API" a povolit ho u tveho API klice
    (APIs & Services -> Credentials -> tvuj klic -> API restrictions).
"""

import argparse
import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# NASTAVENI - tady si muzes hrat
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-6"

# Kdo v poradu pravidelne mluvi. Skript podle obsahu pozna, kdo je kdo,
# a kazdemu pridelí stale stejny hlas napric vsemi epizodami.
ZNAMI_MLUVCI = ["Joe Weisenthal", "Tracy Alloway"]

# Rod pro sklonovani. Bez toho preklad mluvi o zene v muzskem rode.
POHLAVI = {
    "Joe Weisenthal": "muž",
    "Tracy Alloway": "žena",
}

# Nazvy, ktere se casto prekladaji spatne nebo je rozpoznavani reci komoli.
# Vlevo je to, co muze prijit anglicky, vpravo jak to ma znit cesky.
# Sem si pridavej cokoliv, co ti ve vystupu zaskripe.
SLOVNIK = {
    "Odd Lots / Odd Thoughts (přeslech)": "Odd Lots (název pořadu)",
    "Coming to America (film, 1988)": "film Cesta do Ameriky",
    "Brian Colachi / Calacchi / Calachi (přeslech)": "Brian Callaci (jméno hosta)",
    "form factor": "provedení (tvar a velikost zařízení); NIKDY 'form factory' ani 'faktor'",
    "skin (u AI modelu)": "nový kabát",
    "Bloomberg": "Bloomberg",
    "McDonald's": "McDonald's",
    "OpenAI": "OpenAI (jedno slovo, ne 'Open AI')",
    "Apple": "Apple, ale skloňovat: Applu, Applem",
    "Apple (přivlastňovací)": "NEPOUŽÍVAT tvar 'Applův' ani 'Appleův'. "
                              "Místo 'Applův cíl' piš 'cílem Applu je' "
                              "nebo 'cíl společnosti Apple'.",
    "Jony Ive": "Jony Ive, skloňovat: Jonyho Ivea, s Jonym Ivem "
                "(NIKDY 'Johnny Ive' — přeslech z přepisu)",
    "John Ternus": "John Ternus, skloňovat: Johna Ternuse, "
                   "Johnovi Ternusovi (NIKDY 'Ternanus', NIKDY 'Johnu')",
    "Johnu Ternusovi (chybný 3. pád)": "Johnovi Ternusovi — u českého skloňování "
                                       "jména John je 3. pád vždy 'Johnovi', "
                                       "nikdy 'Johnu'",
    "Jared (neexistující osoba)": "V pořadu žádný Jared není. Když v přepisu "
                                  "zazní, jde o přeslech — Joe mluví o sobě "
                                  "a Tracy. Přelož jako 'Tracy a já'.",
    "Tim Cook": "Tim Cook, skloňovat Tima Cooka",
    "Mark Gurman": "Mark Gurman, skloňovat Marka Gurmana",
    "business": "byznys — držet jednotně v celém textu",
    "wearables": "nositelná elektronika",
}

HLASY_PODLE_JMENA = {
    "Joe Weisenthal": "cs-CZ-Chirp3-HD-Sadaltager",  # muz
    "Tracy Alloway": "cs-CZ-Chirp3-HD-Achernar",     # zena
    "Znělka": "cs-CZ-Chirp3-HD-Algenib",             # hlasatel znelky a reklam
}

# Z tohohle se beru hlasy pro hosty a pro kohokoliv dalsiho. Skript si u
# kazdeho hosta necha od Clauda urcit rod a sahne do spravne zasoby, takze
# muz nikdy nedostane zensky hlas.
# Seznam vsech dostupnych hlasu vypises pres --hlasy.
HLASY_MUZI = [
    "cs-CZ-Chirp3-HD-Iapetus",
    "cs-CZ-Chirp3-HD-Charon",
    "cs-CZ-Chirp3-HD-Fenrir",
    "cs-CZ-Chirp3-HD-Schedar",
]

HLASY_ZENY = [
    "cs-CZ-Chirp3-HD-Aoede",
    "cs-CZ-Chirp3-HD-Callirrhoe",
    "cs-CZ-Chirp3-HD-Despina",
    "cs-CZ-Chirp3-HD-Erinome",
]

# Zalozni hlasy, kdyby Chirp3 pro cestinu nebyl dostupny.
# POZOR: Google pro cestinu mimo Chirp3 nabizi jen tyhle dva a oba jsou zenske
# (muzsky Wavenet ani Standard pro cs-CZ neexistuje). Kdyz se na zalohu dojde,
# budou muzi mluvit zenskym hlasem - jina moznost neni.
HLASY_ZALOHA = [
    "cs-CZ-Wavenet-B",
    "cs-CZ-Standard-B",
]

# Vzajemne predstaveni moderatoru rozpoznavani reci pravidelne rozsekne nebo
# zkomoli ("Ja jsem Tracy Alloway a ja jsem Joe Weisenthal"). Misto opravovani
# ho nahradime pevnym textem - v kazde epizode zni stejne.
UVOD_MLUVCI = "Tracy Alloway"
UVOD_TEXT = ("Vítejte u dalšího dílu podcastu Odd Lots. "
             "Já jsem Tracy Alloway a se mnou je tu "
             "Joe Weisenthal.")
UVOD_OKNO = 5        # v kolika prvnich replikach se predstaveni hleda

TEMPO = 1.0          # rychlost reci, 1.0 = normal
VZORKOVACI_FREKVENCE = 24000  # Hz; musi byt stejna u reci i u ticha
PAUZA_MS = 450       # ticho mezi replikami v milisekundach
REPLIK_NA_DAVKU = 12 # kolik replik posilat k prekladu najednou
KOREKTURA_OKNO = 20  # kolik replik posilat najednou ke korekture
UKAZKA_REPLIK = 15   # kolik replik zpracovat v rezimu ukazky

SROVNANI_OKNO = 25   # kolik replik posilat najednou ke srovnani mluvcich

# Pokyny pro srovnani mluvcich. Automaticke rozpoznavani na Omny mluvci plete -
# jednoho cloveka rozdeli na dva, nebo vyrobi "mluvciho", ktery rekne dve slova.
SROVNANI_SYSTEM = """Dostaneš úsek přepisu podcastu. Značky mluvčích v něm \
pocházejí z automatického rozpoznávání a jsou nespolehlivé: jeden člověk bývá \
rozdělený na několik různých značek a občas vznikne mluvčí, který pronese jen \
pár slov uprostřed cizí věty.

Tvůj úkol: u každé repliky urči, kdo ji ve skutečnosti řekl.

Pravidla:
- Řiď se obsahem, ne původními značkami. Kdo na koho reaguje, kdo klade otázky, \
kdo odpovídá, kdo navazuje na vlastní nedokončenou větu.
- Používej jména ze seznamu známých mluvčích, který dostaneš. Hosta, který v \
seznamu není, pojmenuj jeho skutečným jménem, pokud v přepisu zazní, jinak "Host".
- Nevymýšlej nové mluvčí. Když si nejsi jistý, přiřaď repliku tomu, kdo mluvil \
těsně předtím nebo potom.
- Když věta pokračuje přes hranici replik, patří oba kusy jednomu člověku.
- Úvodní znělku pořadu a čtené reklamy (typicky "Bloomberg Audio Studios..." \
nebo upoutávka na sponzora) označ jako "Znělka". Nepřiřazuj je moderátorům.
- Moderátoři se v úvodu představí ("I'm Tracy Alloway", "and I'm Joe Weisenthal"). \
Tohle je ZÁVAZNÉ vodítko — kdo se takhle představí, ten mluví, a od toho odviň \
celý zbytek epizody. Když někdo osloví druhého jménem, mluví ten druhý z dvojice. \
Tracy Alloway je žena a vyrůstala v zahraničí, Joe Weisenthal je muž a je Američan.
- Vzájemné představení moderátorů je v originále jedna plynulá věta ("I'm Tracy \
Alloway... and I'm Joe Weisenthal"), kterou si podávají. Rozpoznávání ji rozsekne \
uprostřed. Přiřaď celé to představení JEDNOMU mluvčímu, ať z toho v češtině \
nevznikne kostrbatá dvojice replik. Totéž udělej u každé věty, kterou dva mluvčí \
zjevně dokončují společně.

Vrať POUZE JSON pole ve tvaru [{"i": 0, "kdo": "Jméno"}, ...] pro každou \
replika v pořadí, v jakém přišla. Žádný úvod, žádné markdown značky."""

# Pokyny pro prekladatele. Tohle je nejdulezitejsi cast celeho skriptu -
# kvalita vysledku stoji a pada na nem. Klidne si ho uprav.
PREKLAD_SYSTEM = """FORMÁT ODPOVĚDI (platí bez ohledu na cokoliv dalšího): \
vracíš POUZE JSON pole českých textů. Žádný úvod, žádné "Tady je překlad:", \
žádné markdown značky, žádný komentář za polem.

Jsi špičkový český dabingový dramaturg. Nepřekládáš slova, \
připravuješ text, který někdo řekne nahlas do mikrofonu. Posluchač nesmí poznat, \
že jde o překlad.

NEJDŮLEŽITĚJŠÍ PRAVIDLO
Nepřekládej po slovech ani po větách. Přečti si celou repliku, pochop, co tím \
člověk chtěl říct, a pak to napiš tak, jak by to řekl Čech. Klidně změň slovosled, \
rozděl souvětí na dvě věty nebo dvě věty spoj. Anglická stavba věty se do češtiny \
nepřenáší.

VSTUP JE ROZSYPANÝ
Anglický text pochází z automatického rozpoznávání řeči a obsahuje chyby: \
přeslechnutá slova, chybějící interpunkci, nedokončené věty. Domysli, co člověk \
doopravdy řekl, a přelož ten smysl. Zjevný přeslech oprav (například "fast food \
chairs" je ve skutečnosti "fast food chains", tedy řetězce).

VÝPLŇKY PRYČ
Angličtina je plná slov, která nic neznamenají: yeah, you know, like, I mean, \
literally, sort of, kind of, right?, so. Do češtiny je nepřekládej. "Literally" \
není "doslova", je to jen důraz. Pokud replika po vyhození výplněk nedává smysl \
sama o sobě, vrať prázdný řetězec "" a obsah nech splynout se sousední replikou.

MLUVENÁ ČEŠTINA
Piš tak, jak lidé mluví, ne jak se píše. Krátké věty. Běžná slova. Můžeš použít \
"teda", "vlastně", "no", "hele" tam, kde to zní přirozeně. Vyhni se knižním \
obratům, přechodníkům a trpnému rodu.

SLOVOSLED
Základní pořádek je podmět – sloveso – předmět, stejně jako když člověk mluví. \
Nepřesouvej předmět před sloveso, pokud na něj opravdu neklademe důraz, a nenechávej \
sloveso až na konci věty. Tohle je nejčastější chyba, které si posluchač všimne.

Špatně: "Já rychlé občerstvení taky mám rád, ale iluze o něm nemám."
Správně: "Já mám rychlé občerstvení taky rád, ale iluze si o něm nedělám."

Špatně: "On tu franšízu za velké peníze koupil."
Správně: "Koupil tu franšízu za velké peníze."

Pointa věty patří na konec — ale docílíš toho tím, že vybereš, co dáš nakonec, \
ne tím, že přeházíš začátek. Než repliku odevzdáš, přečti si ji v duchu nahlas. \
Když ti kdekoliv zaskřípe jazyk, přepiš to.

ROD MLUVČÍHO
U každé repliky dostaneš jméno toho, kdo ji říká, a jeho rod. Slovesa v minulém \
čase, přídavná jména i příčestí skloňuj podle něj. Když mluví žena, píše se \
"vyrůstala jsem", "myslela jsem si", "byla jsem překvapená" — nikdy mužský tvar.

ZÁJMENA ŠETŘI
Angličtina musí psát "he", "they", "I" u každého slovesa, čeština ne. "On chtěl, \
ale oni tvrdili" zní jako titulky z automatu. Napiš prostě "Chtěl si to dělat \
po svém, jenže oni tvrdili něco jiného." Zájmeno použij jen tam, kde je opravdu \
potřeba odlišit, o koho jde.

NÁZVY DĚL
U filmů, knih a písní použij zavedený český název, pokud existuje. A přidej před \
něj slovo, které řekne, o co jde — "film Cesta do Ameriky", "kniha Černá labuť" — \
aby posluchač poznal, že jde o název. Bez toho splyne název s větou.

ROZSYPANÉ VĚTY DOMYSLI
Když je replika v angličtině rozbitá na kusy a nedokončená, nepřenášej tu \
roztříštěnost do češtiny pomlčkami a nedopovězenými větami. Poskládej z toho \
souvislou myšlenku. Čtenář ani posluchač nemá vidět, že tam byl nepořádek.

PŘÍKLADY, JAK TO DĚLAT
Špatně (doslovný překlad): "Byl tam nějaký soudní spor, protože oni tvrdili, \
že on chtěl — ale on chtěl něco jiného."
Správně: "Vedl se kvůli tomu soudní spor. Jim šlo o značku, jenže on si to chtěl \
dělat po svém."

Špatně: "No jo, ale vlastně ano."
Správně: "No jasně, ono to tak vlastně bylo."

Špatně: "Doslova, já vím, mám to rád."
Správně: "Já vím, mám to rád." (slovo "literally" je jen důraz, nepřekládá se)

ODBORNÉ POJMY SE NEOPISUJÍ
Volnost, kterou máš, se týká stavby vět — ne odborných pojmů. Tohle je pořad \
o ekonomice a posluchač termíny očekává. Odborný výraz přelož zavedeným českým \
termínem, nikdy ho nenahrazuj opisem z běžné mluvy.

Špatně: "Zákazníci přijdou sami, značka za tebou stojí."
Správně: "Máš zavedenou zákaznickou základnu a hotové jméno značky."

Špatně: "Firma měla problém, že jí docházely peníze."
Správně: "Firma se dostala do problémů s likviditou."

Jinými slovy: mluv civilně, ale neochuzuj obsah. Když v angličtině zazní termín, \
musí zaznít i v češtině.

UKAZOVACÍ ZÁJMENA ŠETŘI
Nehromaď "to", "tohle", "ten". Tři "to" v jedné větě je spolehlivá známka, že \
větu je potřeba přepsat.

Špatně: "Ale ve skutečnosti to bylo prostě to."
Správně: "Ale ve skutečnosti šlo přesně o tohle."

VAZBY MUSÍ SEDĚT
Sloveso a podstatné jméno spolu musí jít dohromady tak, jak to Čech opravdu říká. \
Význam sám nestačí — hledej ustálenou vazbu, ne první slovo, které se hodí.

Špatně: "Nastupuješ s hotovou zákaznickou základnou."
Správně: "Začínáš s hotovou zákaznickou základnou."

DALŠÍ PRAVIDLA
- Zachovej tón: ironii, nadsázku, když si někdo dělá legraci.
- Jména osob, firem a názvy knih nech v originále.
- Zavedené anglické termíny nech anglicky, když český překlad zní nepřirozeně \
(gig economy, private equity, hedge fund). Ostatní přelož (supply chain = \
dodavatelský řetězec, franchisee = franšízant, franchise = franšíza).
- Čísla piš slovy, jak se čtou: "17 %" jako "sedmnáct procent", "$4.2 billion" \
jako "čtyři celé dvě miliardy dolarů".
- Zkratky, které se hláskují, rozepiš foneticky: "IPO" jako "í pí ou".
- Nepřidávej vysvětlivky ani nic, co v originále nezaznělo.

Dostaneš JSON pole objektů se jménem mluvčího, jeho rodem a anglickým textem. \
Vrať POUZE JSON pole českých textů ve stejném pořadí a počtu (prázdný řetězec \
je platná odpověď u repliky bez obsahu). Žádný úvod, žádné markdown."""

# Korektura je samostatny prubeh nad hotovym ceskym textem. Prekladatel resi smysl
# a stavbu vety a na drobnosti mu uz nezbyva pozornost - tenhle krok je dobira.
KOREKTURA_SYSTEM = """FORMÁT ODPOVĚDI (platí bez ohledu na cokoliv dalšího): \
vracíš POUZE JSON pole opravených textů. Žádný úvod, žádné markdown, žádný komentář.

Jsi pečlivý český korektor. Dostaneš hotový český překlad podcastu. Tvým úkolem \
NENÍ překládat ani přepisovat styl — text už je hotový. Hledáš a opravuješ chyby.

CO OPRAVUJEŠ

1. Cizí abecedu. V textu se nesmí objevit azbuka ani jiné nelatinkové písmo. \
Když na takové slovo narazíš, nahraď ho českým ("история" → "historie").

2. Překlepy, zkomolená a nespisovná slova: "inteligentce" → "inteligence", \
"dvacetipaleový" → "dvacetipalcový", "něco takovéhle" → "něco takového".

2b. Shodu podmětu s přísudkem v čísle: "zbývají jen pár týdnů" → \
"zbývá jen pár týdnů", "mají Apple strop" → "má Apple strop".

3. Chybějící pomocné sloveso u minulého času: "Já pustila telefon" → \
"Já jsem pustila telefon", "Nikdy to neřešila" → "Nikdy jsem to neřešila".

4. Shodu rodu. POZOR, tohle jsou dvě různé situace a nesmíš je zaměnit:
- Mluvčí mluví SÁM O SOBĚ (jednotné číslo) → řídíš se rodem mluvčího, který \
dostaneš. Tracy: "řekla jsem", "byla jsem překvapená". Joe: "řekl jsem".
- Mluvčí mluví O SKUPINĚ, jejíž je součástí (množné číslo) → rod mluvčího \
NEROZHODUJE. Rozhoduje složení skupiny. Když je ve skupině aspoň jeden muž, \
používá se mužský tvar. Tracy mluvící o sobě a Joeovi říká "měli jsme", \
NIKDY "měly jsme" — i když je Tracy žena.
Uvnitř jedné věty nesmí být jednou ženský a jednou mužský tvar téhož podmětu.

5. Pády a slovesné vazby: "Co chce dosáhnout" → "Čeho chce dosáhnout", \
"udělat dominantní hráč" → "udělat dominantního hráče", "svěsil vinu" → \
"svedl vinu", "od Apple" → "od Applu" (cizí jména se v češtině skloňují).

6. Vokalizaci předložek: "v skupinových" → "ve skupinových".

7. Anglická slova. Rozhodni se podle jednoduché zkoušky: řekl by tohle slovo \
česky mluvící odborník, když se o tom baví s kolegou?
- Ano → nech být. Názvy firem a produktů (iPhone, Vision Pro, Gemini), zavedené \
termíny oboru (hyperscaler, foundation model, SKU, roadmapa).
- Ne → přelož. "level" → "úroveň", "skin" → "kabát", "form factor" → \
"tvar a rozměry zařízení".

ZÁKAZ HYBRIDŮ: nikdy nevyrob slovo, které není ani správně anglicky, ani správně \
česky. "form factor" se nesmí stát "form factory" ani "form faktory". Když si \
nejsi jistý, přelož to celé česky, nebo to celé nech anglicky — ale nikdy \
nepřidávej českou koncovku k anglickému kořeni.

Když v textu narazíš na anglický výraz, který zjevně vznikl přeslechem \
z původního přepisu ("form factory" místo "form factor"), domysli, co tam mělo \
stát, a přelož to správně.

8. Věty, které nedávají smysl, protože v nich zůstal nepořádek z původního \
přepisu: "Buď to nepřicházet neviděl" → "Buď to přicházet neviděl", \
"každé druhé dva roky" → "každé dva roky". Domysli, co tam mělo stát.

9. Konzistenci jmen. Když se jedno jméno v textu píše dvěma způsoby \
(Ternus / Ternanus), sjednoť ho na tvar, který převažuje.

CO NEDĚLÁŠ
Neměníš styl, nepřepisuješ dobré věty, nezkracuješ, nepřidáváš. Když je replika \
v pořádku, vrať ji beze změny. Většina replik bude v pořádku — to je normální.

Dostaneš JSON pole objektů se jménem mluvčího, jeho rodem a českým textem. \
Vrať POUZE JSON pole opravených textů ve stejném pořadí a počtu."""


# ---------------------------------------------------------------------------
# ZISKANI PREPISU Z OMNY.FM
# ---------------------------------------------------------------------------

PROHLIZEC = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
}


def je_url(s):
    return bool(re.match(r"https?://", s or "", re.IGNORECASE))


def _segmenty_na_repliky(segmenty, jmena):
    """Z Omny JSONu udela seznam (mluvci, text)."""
    repliky = []
    for seg in segmenty:
        slova = [w.get("text", "") for w in seg.get("words", [])]
        text = " ".join(x for x in slova if x).strip()
        if not text:
            continue
        i = seg.get("speaker", 0)
        kdo = jmena[i] if 0 <= i < len(jmena) else f"speaker {i + 1}"
        repliky.append((kdo.strip().lower(), text))
    return repliky


def _odescapuj(s):
    return s.replace("\\u0026", "&").replace("\\/", "/")


def omny_najdi_klip(html, slug):
    """Z HTML stranky vytahne udaje o epizode, ktera odpovida slugu z URL.

    Stranka nese vlozeny JSON se vsemi klipy z postranniho seznamu, takze
    nestaci vzit prvni nalezene ID - musime najit to se spravnym slugem.

    Jednotliva pole klipu jsou v HTML rozhazena (AudioUrl byva uplne jinde nez
    Id), takze se nespolehame na jejich poradi. Chytame se toho, ze ID epizody
    je obsazene primo v adresach prepisu i zvuku.
    """
    clip_id = None
    for m in re.finditer(r'"Id":"([0-9a-f-]{36})"(.{0,2000}?)"Slug":"([^"]+)"', html, re.S):
        if m.group(3) == slug:
            clip_id = m.group(1)
            break
    if not clip_id:
        return None

    # adresa prepisu - hledame tu, ktera obsahuje ID nasi epizody
    prepis_url, publikovany = None, False
    mp = re.search(r'"TranscriptUrl":"([^"]*' + re.escape(clip_id) + r'[^"]*)"', html)
    if mp:
        prepis_url = _odescapuj(mp.group(1))
        # priznak stoji hned za adresou
        okoli = html[mp.end():mp.end() + 300]
        publikovany = '"HasPublishedTranscript":true' in okoli

    # kdyby TranscriptUrl chybel, slozime ho z ID organizace a ID klipu
    if not prepis_url:
        mo = re.search(r'"OrganizationId":"([0-9a-f-]{36})"', html)
        if mo:
            prepis_url = (f"https://api.omny.fm/orgs/{mo.group(1)}"
                          f"/clips/{clip_id}/transcript")
            publikovany = True   # nevime, zkusime to a uvidime

    # adresa zvuku - taky obsahuje ID epizody
    audio_url = None
    ma = re.search(r'"AudioUrl":"([^"]*' + re.escape(clip_id) + r'[^"]*)"', html)
    if not ma:
        ma = re.search(r'"(https?://[^"]*' + re.escape(clip_id) + r'[^"]*audio\.mp3)"', html)
    if ma:
        audio_url = _odescapuj(ma.group(1))

    return {
        "id": clip_id,
        "prepis_url": prepis_url,
        "publikovany": publikovany,
        "audio_url": audio_url,
    }


def omny_primy_mp3(audio_url):
    """Odizoluje sledovaci presmerovani a vrati primou adresu na traffic.omny.fm."""
    if not audio_url:
        return None
    m = re.search(r"(https?://)?(traffic\.omny\.fm/d/clips/.+?audio\.mp3)", audio_url)
    if m:
        return "https://" + m.group(2)
    return audio_url


def omny_ziskej(url):
    """Stahne stranku epizody a vrati (repliky, info). Repliky jsou None,
    kdyz epizoda publikovany prepis nema - pak se jde na zvukovou zalohu."""
    slug = url.rstrip("/").split("/")[-1].split("?")[0]
    print(f"Stahuji stránku epizody ({slug})...")

    try:
        r = requests.get(url, headers=PROHLIZEC, timeout=60)
    except requests.exceptions.RequestException as e:
        sys.exit(f"Na tu adresu se nepodařilo připojit.\n"
                 f"Zkontroluj, že je správně opsaná a že funguje internet.\n"
                 f"({type(e).__name__})")
    if r.status_code == 404:
        sys.exit("Epizoda na téhle adrese neexistuje (404). Zkontroluj adresu.")
    if r.status_code != 200:
        sys.exit(f"Stránku epizody se nepodařilo stáhnout ({r.status_code}).")

    info = omny_najdi_klip(r.text, slug)
    if not info:
        sys.exit("V HTML stránky jsem nenašel data té epizody. "
                 "Zkontroluj, že URL vede přímo na epizodu, ne na přehled pořadu.")

    info["mp3"] = omny_primy_mp3(info.get("audio_url"))

    if not info.get("prepis_url") or not info.get("publikovany"):
        print("  epizoda nemá publikovaný přepis.")
        return None, info

    print("  stahuji přepis...")
    tr = requests.get(info["prepis_url"], headers=PROHLIZEC, timeout=180)
    if tr.status_code != 200:
        print(f"  ! přepis se nepodařilo stáhnout ({tr.status_code})")
        return None, info

    try:
        data = tr.json()
        jmena = [s.get("name", "") for s in data.get("speakers", [])]
        repliky = _segmenty_na_repliky(data.get("segments", []), jmena)
    except (ValueError, KeyError, TypeError) as e:
        print(f"  ! přepis má neočekávaný tvar ({e})")
        return None, info

    if not repliky:
        print("  ! přepis je prázdný")
        return None, info

    print(f"  hotovo, {len(repliky)} úseků od {len(jmena)} mluvčích.")
    return repliky, info


# ---------------------------------------------------------------------------
# ZALOZNI CESTA: PREPIS ZVUKU PRES GOOGLE SPEECH-TO-TEXT
# ---------------------------------------------------------------------------

STT_USEK_S = 540      # delka jednoho useku v sekundach (9 minut)
STT_JAZYK = "en-US"
STT_MAX_MLUVCICH = 6


def _stahni_mp3(url, cil):
    print(f"Stahuji zvuk...")
    with requests.get(url, headers=PROHLIZEC, stream=True, timeout=600) as r:
        if r.status_code != 200:
            sys.exit(f"Zvuk se nepodařilo stáhnout ({r.status_code}).")
        staz = 0
        with cil.open("wb") as f:
            for kus in r.iter_content(chunk_size=1 << 20):
                f.write(kus)
                staz += len(kus)
                print(f"\r  {staz / 1048576:.1f} MB", end="", flush=True)
    print()
    return cil


def _delka_zvuku(cesta):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(cesta)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        sys.exit("Nepodařilo se zjistit délku zvuku (ffprobe).")


def _usek_na_flac(mp3, tmp, od, delka, poradi):
    """Vyrizne usek a prevede na mono FLAC 16 kHz - to Google chce
    a zaroven se tak vejdeme do limitu na velikost pozadavku."""
    cil = tmp / f"stt_{poradi:03d}.flac"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(od), "-t", str(delka), "-i", str(mp3),
         "-ac", "1", "-ar", "16000", "-c:a", "flac", str(cil)],
        check=True, capture_output=True,
    )
    return cil


def _stt_usek(flac, klic):
    """Posle jeden usek na rozpoznani a pocka na vysledek."""
    zvuk = base64.b64encode(flac.read_bytes()).decode("ascii")

    telo = {
        "config": {
            "encoding": "FLAC",
            "sampleRateHertz": 16000,
            "languageCode": STT_JAZYK,
            "enableAutomaticPunctuation": True,
            "model": "latest_long",
            "diarizationConfig": {
                "enableSpeakerDiarization": True,
                "minSpeakerCount": 2,
                "maxSpeakerCount": STT_MAX_MLUVCICH,
            },
        },
        "audio": {"content": zvuk},
    }

    r = requests.post(
        "https://speech.googleapis.com/v1/speech:longrunningrecognize",
        params={"key": klic}, json=telo, timeout=300,
    )
    if r.status_code != 200:
        sys.exit(
            f"Chyba Speech-to-Text ({r.status_code}): {r.text[:500]}\n\n"
            "Nejčastější příčina: v Google Cloud není zapnuté "
            "'Cloud Speech-to-Text API', nebo ho tvůj API klíč nemá povolené "
            "(APIs & Services -> Credentials -> klíč -> API restrictions)."
        )

    operace = r.json().get("name")
    if not operace:
        sys.exit(f"Speech-to-Text nevrátil číslo úlohy: {r.text[:300]}")

    # cekame na dokonceni
    cekano = 0
    while True:
        time.sleep(10)
        cekano += 10
        s = requests.get(
            f"https://speech.googleapis.com/v1/operations/{operace}",
            params={"key": klic}, timeout=60,
        )
        if s.status_code != 200:
            sys.exit(f"Chyba při čekání na přepis ({s.status_code}): {s.text[:300]}")
        stav = s.json()
        if stav.get("done"):
            break
        print(f"\r    přepisuji... {cekano} s", end="", flush=True)
        if cekano > 3600:
            sys.exit("Přepis úseku trvá přes hodinu, něco je špatně.")
    print("\r" + " " * 40 + "\r", end="")

    if "error" in stav:
        sys.exit(f"Speech-to-Text selhal: {stav['error']}")

    return stav.get("response", {}).get("results", [])


def _slova_na_repliky(slova, posun_mluvcich):
    """Slova se speakerTag posklada do souvislych replik."""
    repliky = []
    kdo, buffer = None, []

    def uloz():
        if buffer:
            t = " ".join(buffer).strip()
            if t:
                repliky.append((f"speaker {kdo + posun_mluvcich}", t))

    for w in slova:
        tag = int(w.get("speakerTag", 1))
        text = w.get("word", "")
        if not text:
            continue
        if tag != kdo:
            uloz()
            buffer = []
            kdo = tag
        buffer.append(text)
    uloz()
    return repliky


def prepis_zvuk(mp3_url, klic, tmp):
    """Stahne MP3 a nechá ho prepsat pres Google Speech-to-Text.

    Dlouhy zvuk delime na useky - Google ma limit na velikost pozadavku.
    Cislovani mluvcich se mezi useky neshoduje, ale to nevadi: skript pak
    stejne pousti srovnani mluvcich pres Claude, ktere je poskláda podle obsahu.
    """
    if not mp3_url:
        sys.exit("Nenašel jsem adresu MP3, takže nemám co přepsat.")

    mp3 = _stahni_mp3(mp3_url, tmp / "epizoda.mp3")
    delka = _delka_zvuku(mp3)
    pocet = max(1, math.ceil(delka / STT_USEK_S))
    print(f"Zvuk má {delka / 60:.1f} min, rozdělím na {pocet} úseků.")

    vsechny = []
    posun = 1
    for i in range(pocet):
        od = i * STT_USEK_S
        d = min(STT_USEK_S, delka - od)
        print(f"  úsek {i + 1}/{pocet}...")
        flac = _usek_na_flac(mp3, tmp, od, d, i)
        vysledky = _stt_usek(flac, klic)
        flac.unlink(missing_ok=True)

        # pri zapnute diarizaci nese kompletni seznam slov az posledni vysledek
        slova = []
        for v in vysledky:
            alt = (v.get("alternatives") or [{}])[0]
            if alt.get("words"):
                slova = alt["words"]
        if not slova:
            print("    ! v tomhle úseku nic nerozpoznal, přeskakuji")
            continue

        casti = _slova_na_repliky(slova, posun)
        vsechny.extend(casti)
        # aby se mluvci z ruznych useku nepletli dohromady
        posun += STT_MAX_MLUVCICH

    mp3.unlink(missing_ok=True)

    if not vsechny:
        sys.exit("Speech-to-Text nevrátil žádný text.")

    print(f"Přepsáno: {len(vsechny)} úseků.")
    return vsechny


# ---------------------------------------------------------------------------

def nacti_repliky(cesta):
    """Rozparsuje transkript z Omny na seznam (mluvci, text)."""
    text = Path(cesta).read_text(encoding="utf-8")

    # Omny sype transkript ruzne podle toho, jak ho zkopirujes. Zvladneme
    # "Speaker 1: text", "Speaker 1\n00:15\ntext" i "SPEAKER 1 - text".
    vzor = re.compile(
        r"^\s*(speaker\s*\d+|mluv[cč][ií]\s*\d+)\s*[:\-–]?\s*$"
        r"|^\s*(speaker\s*\d+|mluv[cč][ií]\s*\d+)\s*[:\-–]\s*(.+)$",
        re.IGNORECASE,
    )
    cas = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?\s*$")

    repliky, mluvci, buffer = [], None, []

    def uloz():
        if mluvci and buffer:
            spojeno = " ".join(buffer).strip()
            if spojeno:
                repliky.append((mluvci, spojeno))

    for radek in text.splitlines():
        if cas.match(radek):
            continue
        m = vzor.match(radek)
        if m:
            uloz()
            buffer = []
            mluvci = (m.group(1) or m.group(2)).strip().lower()
            mluvci = re.sub(r"\s+", " ", mluvci)
            if m.group(3):
                buffer.append(m.group(3).strip())
        elif radek.strip():
            buffer.append(radek.strip())
    uloz()

    if not repliky:
        # Zadne znacky mluvcich - bereme to jako jeden hlas po odstavcich
        odstavce = [o.strip() for o in re.split(r"\n\s*\n", text) if o.strip()]
        repliky = [("speaker 1", o) for o in odstavce]

    return repliky


POKUSU = 5           # kolik pokusu na jedno volani API
CEKANI_ZAKLAD = 4    # zaklad exponencialniho cekani v sekundach

# Odpovedi, ktere znamenaji "zkus to za chvili znovu", ne "je to spatne".
# 429 = moc rychle za sebou, 529 = server pretizeny, 5xx = vypadek na jejich strane.
DOCASNE_CHYBY = (408, 429, 500, 502, 503, 504, 529)


def _s_opakovanim(popis, poslat, napoveda=""):
    """Zavola API a pri docasne chybe to zkusi znovu.

    Bez tohohle staci jedno pretizeni serveru a spadne cely prevod epizody -
    vcetne uz zaplaceneho prekladu. Cekame exponencialne dlouho: 4, 8, 16, 32 s.
    """
    for pokus in range(1, POKUSU + 1):
        try:
            r = poslat()
        except requests.exceptions.RequestException as e:
            if pokus == POKUSU:
                sys.exit(f"{popis}: spojení opakovaně selhalo ({type(e).__name__}).\n"
                         "Zkontroluj internet a pusť to znovu.")
            cekej = CEKANI_ZAKLAD * (2 ** (pokus - 1))
            print(f"\n    ! spojení selhalo, zkusím to za {cekej} s "
                  f"(pokus {pokus} z {POKUSU})", flush=True)
            time.sleep(cekej)
            continue

        if r.status_code == 200:
            return r

        if r.status_code in DOCASNE_CHYBY and pokus < POKUSU:
            cekej = CEKANI_ZAKLAD * (2 ** (pokus - 1))
            try:                       # server nekdy sam rekne, jak dlouho cekat
                cekej = max(cekej, int(float(r.headers.get("retry-after", 0))))
            except (TypeError, ValueError):
                pass
            print(f"\n    ! server odpověděl {r.status_code}, zkusím to za "
                  f"{cekej} s (pokus {pokus} z {POKUSU})", flush=True)
            time.sleep(cekej)
            continue

        sys.exit(f"{popis} ({r.status_code}): {r.text[:400]}" +
                 (f"\n\n{napoveda}" if napoveda else ""))

    sys.exit(f"{popis}: server je opakovaně nedostupný. Zkus to za chvíli znovu.")


def _vytahni_json(text):
    """Vyloupne JSON z odpovedi modelu.

    Model ma vracet holy JSON, ale obcas ho zabali do markdownu nebo pred nej
    napise "Tady je překlad:". Odrizneme vsechno pred prvni zavorkou a za
    posledni, at nas jedna zdvorila veta nepolozi.
    """
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    if t.startswith("[") or t.startswith("{"):
        return t
    zac = min((i for i in (t.find("["), t.find("{")) if i != -1), default=-1)
    kon = max(t.rfind("]"), t.rfind("}"))
    if zac != -1 and kon > zac:
        return t[zac:kon + 1].strip()
    return t


def _claude(system, uzivatel, klic, max_tokens=8000, teplota=None):
    """Jedno zavolani Claude API, vraci text odpovedi.

    teplota=0 vypne nahodnost. Pouziva se u uloh, kde chceme pokazde stejny
    vysledek (korektura, urcovani mluvcich). U prekladu se nechava vychozi,
    protoze tam model potrebuje volit mezi formulacemi.
    """
    telo = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": uzivatel}],
    }
    if teplota is not None:
        telo["temperature"] = teplota

    r = _s_opakovanim("Chyba API", lambda: requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": klic,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=telo,
        timeout=180,
    ))
    return _vytahni_json(r.json()["content"][0]["text"])


def srovnej_mluvci(repliky, klic):
    """Nahradi nespolehlive znacky Speaker N skutecnymi jmeny."""
    znami = list(ZNAMI_MLUVCI)
    vysledek = []

    for i in range(0, len(repliky), SROVNANI_OKNO):
        okno = repliky[i:i + SROVNANI_OKNO]

        # posledni tri uz srovnane repliky jako kontext
        kontext = ""
        if vysledek:
            kontext = "Předchozí repliky a komu byly přiřazeny:\n"
            for kdo, txt in vysledek[-3:]:
                kontext += f"- {kdo}: {txt[:120]}\n"
            kontext += "\n"

        data = [
            {"i": j, "puvodni_znacka": m, "text": t}
            for j, (m, t) in enumerate(okno)
        ]
        uzivatel = (
            f"Známí mluvčí: {', '.join(znami)}\n\n"
            + kontext
            + "Repliky:\n"
            + json.dumps(data, ensure_ascii=False)
        )

        print(f"  srovnávám mluvčí {i + 1}-{i + len(okno)} z {len(repliky)}...")
        syrove = _claude(SROVNANI_SYSTEM, uzivatel, klic, teplota=0)

        try:
            prirazeni = json.loads(syrove)
            mapa = {int(z["i"]): str(z["kdo"]).strip() for z in prirazeni}
        except (json.JSONDecodeError, KeyError, ValueError):
            print("  ! srovnání selhalo, nechávám původní značky")
            mapa = {}

        for j, (puvodni, txt) in enumerate(okno):
            kdo = mapa.get(j) or puvodni
            if kdo not in znami and not kdo.lower().startswith("speaker"):
                znami.append(kdo)
            vysledek.append((kdo, txt))

    return vysledek


ROD_SYSTEM = """Dostaneš jména mluvčích z podcastu a k nim ukázky: co sami \
řekli a jak o nich mluví ostatní.

Tvůj úkol: u každého urči rod, aby mu šel přidělit odpovídající hlas a aby \
česká slovesa v minulém čase byla ve správném tvaru.

Pravidla:
- Řiď se tím, jak o mluvčím mluví ostatní ("he is", "she said", "his book").
  To je nejspolehlivější vodítko.
- Nehádej podle jména. Jména bývají matoucí a v cizích jazycích ještě víc.
- Když opravdu není z čeho poznat, vrať "neznámý". Nevymýšlej si.

Vrať POUZE JSON objekt ve tvaru {"Jméno": "muž"} nebo {"Jméno": "žena"} \
nebo {"Jméno": "neznámý"} pro každé jméno, které dostaneš. Žádný úvod, \
žádné markdown značky."""


def urci_rody(repliky, klic):
    """Zjisti rod u mluvcich, ktere neznáme z nastaveni.

    Moderatore mame v POHLAVI natvrdo, ale host je pokazde jiny. Bez tohohle
    by host dostal hlas podle poradi - klidne zensky - a preklad by o nem
    mluvil v muzskem rode.
    """
    poradi = []
    for m, _ in repliky:
        if m not in poradi:
            poradi.append(m)
    neznami = [m for m in poradi
               if m not in POHLAVI and m not in HLASY_PODLE_JMENA]
    if not neznami:
        return {}

    podklady = []
    for kdo in neznami:
        vlastni = [t for m, t in repliky if m == kdo][:3]
        # jak o nem mluvi ostatni - hledame podle jednotlivych slov ze jmena
        casti = [c for c in re.split(r"\s+", kdo) if len(c) > 2]
        o_nem = []
        for m, t in repliky:
            if m == kdo or len(o_nem) >= 5:
                continue
            if any(re.search(rf"\b{re.escape(c)}", t, re.IGNORECASE) for c in casti):
                o_nem.append(t[:400])
        podklady.append({
            "jmeno": kdo,
            "co_rekl": [t[:300] for t in vlastni],
            "jak_o_nem_mluvi_ostatni": o_nem,
        })

    print(f"  zjišťuji rod: {', '.join(neznami)}")
    syrove = _claude(ROD_SYSTEM, json.dumps(podklady, ensure_ascii=False),
                     klic, max_tokens=1000)

    try:
        rody = json.loads(syrove)
        if not isinstance(rody, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        print("  ! rod se určit nepodařilo, beru mužský hlas")
        return {}

    vysledek = {}
    for kdo in neznami:
        r = str(rody.get(kdo, "")).strip().lower()
        if r in ("muž", "žena"):
            vysledek[kdo] = r
            print(f"    {kdo}: {r}")
        else:
            print(f"    {kdo}: nepoznáno, beru mužský hlas")
    return vysledek


# "Ja jsem Tracy Alloway", "Jsem Joe Weisenthal" - prijmeni v 1. pade tesne
# za slovesem. Sklonovane tvary ("s Joem Weisenthalem") schvalne nechytame.
UVOD_VZOR = re.compile(
    r"\b(?:já\s+)?jsem\b[^.!?]{0,40}?\b(?:Alloway|Weisenthal)\b",
    re.IGNORECASE,
)


def sjednot_uvod(repliky):
    """Nahradi vzajemne predstaveni moderatoru jednim pevnym textem.

    Hleda v prvnich UVOD_OKNO replikach ty, kde se nekdo predstavuje jmenem.
    Vsechny takove zahodi a na misto te prvni vlozi UVOD_TEXT. Nezalezi na tom,
    kdo se predstavi drive ani jestli jsou obe predstaveni v jedne replice.
    Znelku nechava byt.
    """
    najite = [
        i for i, (kdo, t) in enumerate(repliky[:UVOD_OKNO])
        if kdo != "Znělka" and UVOD_VZOR.search(t)
    ]
    if not najite:
        return repliky

    kam = najite[0]           # nejnizsi index, pred nim se nic nemaze
    zbytek = [r for i, r in enumerate(repliky) if i not in set(najite)]
    zbytek.insert(kam, (UVOD_MLUVCI, UVOD_TEXT))

    cisla = ", ".join(str(i + 1) for i in najite)
    print(f"  úvod: replika {cisla} nahrazena pevným textem "
          f"({UVOD_MLUVCI})")
    return zbytek


def slouc_navazujici(repliky):
    """Spoji za sebou jdouci repliky stejneho cloveka do jedne."""
    if not repliky:
        return repliky
    spojene = [list(repliky[0])]
    for kdo, txt in repliky[1:]:
        if kdo == spojene[-1][0]:
            spojene[-1][1] = (spojene[-1][1].rstrip() + " " + txt.lstrip()).strip()
        else:
            spojene.append([kdo, txt])
    return [tuple(x) for x in spojene]


def zkorektorovat(repliky, klic, rody=None):
    """Projde hotovy cesky text a opravi preklepy, pady, rody a anglicke zbytky."""
    if rody is None:
        rody = POHLAVI
    vysledek = []

    for i in range(0, len(repliky), KOREKTURA_OKNO):
        okno = repliky[i:i + KOREKTURA_OKNO]
        data = [
            {"kdo": m, "rod": rody.get(m, "neznámý"), "text": t}
            for m, t in okno
        ]

        print(f"  korektura {i + 1}-{i + len(okno)} z {len(repliky)}...")
        uzivatel = ""
        if SLOVNIK:
            uzivatel += "Závazné znění názvů a pojmů:\n"
            uzivatel += "\n".join(f"- {a} → {b}" for a, b in SLOVNIK.items())
            uzivatel += "\n\n"
        uzivatel += "Zkontroluj a oprav:\n" + json.dumps(data, ensure_ascii=False)

        syrove = _claude(KOREKTURA_SYSTEM, uzivatel, klic, teplota=0)

        try:
            opravene = json.loads(syrove)
        except json.JSONDecodeError:
            print("  ! korektura selhala, nechávám původní text")
            vysledek.extend(okno)
            continue

        if len(opravene) != len(okno):
            print(f"  ! čekal jsem {len(okno)} replik, přišlo {len(opravene)}")
            vysledek.extend(okno)
            continue

        zmeneno = 0
        for (kdo, puvodni), novy in zip(okno, opravene):
            novy = str(novy).strip()
            if novy and novy != puvodni:
                zmeneno += 1
            vysledek.append((kdo, novy or puvodni))
        if zmeneno:
            print(f"    opraveno {zmeneno} replik")

    return vysledek


PREKLAD_MAX_TOKENS = 16000   # strop delky odpovedi prekladatele


def _preloz_davku(davka, kontext, klic, rody=None):
    """Prelozi jednu davku a vrati seznam ceskych textu.

    Dlouhe slouceni repliky umi vyrobit odpoved, ktera se do stropu nevejde -
    pak ji API usekne uprostred a JSON se rozbije. V takovem pripade davku
    rozpulime a zkusime to znovu. Stejne se zachovame, kdyz odpoved nesedi
    poctem: kratsi davka drzi prirazeni k mluvcim spolehliveji.
    """
    if rody is None:
        rody = POHLAVI
    texty = [
        {"kdo": m, "rod": rody.get(m, "neznámý"), "text": t}
        for m, t in davka
    ]

    uzivatel = ""
    if SLOVNIK:
        uzivatel += "Závazné znění názvů:\n"
        uzivatel += "\n".join(f"- {a} → {b}" for a, b in SLOVNIK.items())
        uzivatel += "\n\n"
    if kontext:
        uzivatel += f"Pro kontext, předchozí přeložená pasáž:\n{kontext}\n\n"
    uzivatel += "Přelož tyto repliky:\n" + json.dumps(texty, ensure_ascii=False)

    r = _s_opakovanim("Chyba překladu", lambda: requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": klic,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": PREKLAD_MAX_TOKENS,
            "system": PREKLAD_SYSTEM,
            "messages": [{"role": "user", "content": uzivatel}],
        },
        timeout=300,
    ))

    odpoved = r.json()
    useknuto = odpoved.get("stop_reason") == "max_tokens"

    prelozene = None
    if not useknuto:
        try:
            prelozene = json.loads(_vytahni_json(odpoved["content"][0]["text"]))
            if not isinstance(prelozene, list):
                prelozene = None
        except json.JSONDecodeError:
            prelozene = None

    # nepovedlo se - zkusime to na mensi davce
    if prelozene is None or len(prelozene) != len(davka):
        if len(davka) > 1:
            if useknuto:
                duvod = "odpověď se nevešla do limitu"
            elif prelozene is None:
                duvod = "odpověď nebyla platný JSON"
            else:
                duvod = f"přišlo {len(prelozene)} textů místo {len(davka)}"
            print(f"    ! {duvod}, dělím dávku na dvě a zkouším znovu")
            pul = len(davka) // 2
            prvni = _preloz_davku(davka[:pul], kontext, klic, rody)
            novy_kontext = " ".join(x for x in prvni[-3:] if x)[:900] or kontext
            druha = _preloz_davku(davka[pul:], novy_kontext, klic, rody)
            return prvni + druha

        # jedina replika - dal uz delit nejde
        if useknuto or prelozene is None:
            ukazka = davka[0][1][:120]
            sys.exit(
                "Jedna replika je tak dlouhá, že se její překlad nevejde do "
                f"limitu {PREKLAD_MAX_TOKENS} tokenů.\n"
                f"Začíná takhle: {ukazka}...\n"
                "Zvyš PREKLAD_MAX_TOKENS v nastavení skriptu."
            )
        # model repliku rozdelil na vic textu - slepime je zpatky
        return [" ".join(x for x in prelozene if x).strip()]

    return prelozene


def prelozit(repliky, klic, rody=None):
    """Prelozi repliky po davkach. Predava kontext, aby drzela navaznost."""
    vysledek = []
    kontext = ""

    for i in range(0, len(repliky), REPLIK_NA_DAVKU):
        davka = repliky[i:i + REPLIK_NA_DAVKU]
        print(f"  překládám repliky {i + 1}-{i + len(davka)} z {len(repliky)}...")

        prelozene = _preloz_davku(davka, kontext, klic, rody)

        for (mluvci, _), cesky in zip(davka, prelozene):
            vysledek.append((mluvci, cesky))

        kontext = " ".join(p for p in prelozene[-3:] if p)[:900]

    return vysledek


def dostupne_hlasy(klic):
    r = _s_opakovanim("Nepodařilo se načíst hlasy", lambda: requests.get(
        "https://texttospeech.googleapis.com/v1/voices",
        params={"key": klic, "languageCode": "cs-CZ"},
        timeout=60,
    ))
    return [v["name"] for v in r.json().get("voices", [])]


def rozdel_text(text, limit=4000):
    """Google bere max ~5000 bajtu na pozadavek. Delime po vetach."""
    if len(text.encode("utf-8")) <= limit:
        return [text]
    kusy, akt = [], ""
    for veta in re.split(r"(?<=[.!?…])\s+", text):
        if len((akt + " " + veta).encode("utf-8")) > limit and akt:
            kusy.append(akt.strip())
            akt = veta
        else:
            akt = (akt + " " + veta).strip()
    if akt:
        kusy.append(akt)
    return kusy


def namluv(text, hlas, klic, tmp, index):
    """Namluvi jednu repliku. Vraci seznam cest k WAV souborum.

    Dlouhy text se deli na kusy, ale kazdy kus se uklada jako samostatny
    soubor. Bajtove slepovani zvukovych souboru delalo na spojich lupance -
    kazdy soubor ma vlastni hlavicku a technicke ticho na okrajich.
    Slepeni proto delame az na konci pres ffmpeg.
    """
    cesty = []
    for j, kus in enumerate(rozdel_text(text)):
        telo = {
            "input": {"text": kus},
            "voice": {"languageCode": "cs-CZ", "name": hlas},
            "audioConfig": {
                "audioEncoding": "LINEAR16",
                "sampleRateHertz": VZORKOVACI_FREKVENCE,
                "speakingRate": TEMPO,
            },
        }
        r = _s_opakovanim("Chyba TTS", lambda: requests.post(
            "https://texttospeech.googleapis.com/v1/text:synthesize",
            params={"key": klic},
            json=telo,
            timeout=180,
        ))

        data = base64.b64decode(r.json()["audioContent"])

        # Google vraci LINEAR16 zabalene do WAV. Kdyby prislo hole PCM,
        # doplnime hlavicku sami, at ffmpeg vi, s cim pracuje.
        if data[:4] != b"RIFF":
            cil = tmp / f"{index:05d}_{j:02d}.pcm"
            cil.write_bytes(data)
            wav = tmp / f"{index:05d}_{j:02d}.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-f", "s16le", "-ar", str(VZORKOVACI_FREKVENCE),
                 "-ac", "1", "-i", str(cil), str(wav)],
                check=True, capture_output=True,
            )
            cesty.append(wav)
        else:
            cil = tmp / f"{index:05d}_{j:02d}.wav"
            cil.write_bytes(data)
            cesty.append(cil)

    return cesty


def slep(skupiny, vystup, tmp):
    """Prolozi repliky tichem, vyrovna hlasitost a slepi do jednoho MP3.

    skupiny = seznam seznamu; kazdy vnitrni seznam jsou kusy jedne repliky.
    Ticho se vklada jen mezi repliky, ne mezi kusy jedne repliky.
    """
    ticho = tmp / "ticho.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r={VZORKOVACI_FREKVENCE}:cl=mono",
         "-t", str(PAUZA_MS / 1000), str(ticho)],
        check=True, capture_output=True,
    )

    seznam = tmp / "seznam.txt"
    with seznam.open("w", encoding="utf-8") as f:
        for kusy in skupiny:
            for kus in kusy:
                f.write(f"file '{kus.resolve().as_posix()}'\n")
            f.write(f"file '{ticho.resolve().as_posix()}'\n")

    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(seznam),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-c:a", "libmp3lame", "-b:a", "128k", str(vystup)],
        check=True, capture_output=True,
    )


def main():
    p = argparse.ArgumentParser(description="Vyrobí českou verzi podcastu z epizody na omny.fm.")
    p.add_argument("zdroj", nargs="?",
                   help="URL epizody z omny.fm, nebo textový soubor s transkriptem")
    p.add_argument("--full", action="store_true", help="zpracovat celou epizodu (jinak jen ukázku)")
    p.add_argument("--vystup", default="epizoda_cz.mp3", help="název výsledného MP3")
    p.add_argument("--hlasy", action="store_true", help="jen vypsat dostupné české hlasy")
    p.add_argument("--bez-srovnani", action="store_true",
                   help="přeskočit srovnání mluvčích (rychlejší, ale hlasy budou skákat)")
    p.add_argument("--bez-korektury", action="store_true",
                   help="přeskočit korekturu hotového překladu")
    args = p.parse_args()

    ant = os.environ.get("ANTHROPIC_API_KEY")
    goo = os.environ.get("GOOGLE_TTS_KEY")

    if args.hlasy:
        if not goo:
            sys.exit("Chybí GOOGLE_TTS_KEY.")
        for h in dostupne_hlasy(goo):
            print(h)
        return

    if not args.zdroj:
        sys.exit("Chybí zdroj. Zkus: python podcast_cz.py https://omny.fm/shows/...")
    if not ant:
        sys.exit("Chybí ANTHROPIC_API_KEY.")
    if not goo:
        sys.exit("Chybí GOOGLE_TTS_KEY.")
    try:
        if subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0:
            raise FileNotFoundError
    except (FileNotFoundError, OSError):
        sys.exit("Nenašel jsem ffmpeg. Nainstaluj ho a zkus znovu.")

    if je_url(args.zdroj):
        repliky, info = omny_ziskej(args.zdroj)
        if repliky is None:
            print("\nZkusím záložní cestu: přepsat zvuk přes Google Speech-to-Text.")
            with tempfile.TemporaryDirectory() as td:
                repliky = prepis_zvuk(info.get("mp3"), goo, Path(td))
    else:
        repliky = nacti_repliky(args.zdroj)

    print(f"Načteno {len(repliky)} replik.")

    if not args.full:
        repliky = repliky[:UKAZKA_REPLIK]
        print(f"Režim ukázky: zpracuju prvních {len(repliky)}. Celou epizodu pustíš přes --full.")

    znaku = sum(len(t) for _, t in repliky)
    print(f"Zhruba {znaku} znaků. Odhad ceny: překlad ~${znaku / 1000 * 0.006:.2f}, "
          f"hlas ~${znaku / 1_000_000 * 30:.2f} (Chirp3, mimo free tier).")

    if not args.bez_srovnani:
        print("\nSrovnávám mluvčí...")
        repliky = srovnej_mluvci(repliky, ant)
        pred = len(repliky)
        repliky = slouc_navazujici(repliky)
        print(f"  {pred} replik sloučeno na {len(repliky)}.")

    # u hostu, ktere neznáme z nastaveni, si necháme urcit rod - potrebujeme
    # ho jak na vyber hlasu, tak na spravne tvary sloves v prekladu
    rody = dict(POHLAVI)
    rody.update(urci_rody(repliky, ant))

    # obsazeni hlasu - znami mluvci maji stale stejny hlas, ostatni dostanou
    # volny hlas ze zasoby podle sveho rodu
    poradi = []
    for m, _ in repliky:
        if m not in poradi:
            poradi.append(m)

    k_dispozici = dostupne_hlasy(goo)
    chirp_ok = (HLASY_MUZI[0] in k_dispozici and HLASY_ZENY[0] in k_dispozici)
    if not chirp_ok:
        print("Chirp3-HD pro češtinu nedostupný, beru záložní hlasy.")
        print("  ! záložní hlasy jsou jen ženské, muži budou znít žensky.")

    obsazeni, volne = {}, {"muž": 0, "žena": 0}
    for m in poradi:
        pevny = HLASY_PODLE_JMENA.get(m)
        if pevny and chirp_ok and pevny in k_dispozici:
            obsazeni[m] = pevny
            continue
        rod = rody.get(m, "muž")          # kdyz rod neznáme, bereme muzsky
        if not chirp_ok:
            sada = HLASY_ZALOHA
        else:
            sada = HLASY_ZENY if rod == "žena" else HLASY_MUZI
        obsazeni[m] = sada[volne[rod] % len(sada)]
        volne[rod] += 1

    print("\nObsazení:")
    for m, h in obsazeni.items():
        znacka = f"  ({rody[m]})" if m in rody else ""
        print(f"  {m} -> {h}{znacka}")

    print("\nPřekládám...")
    cesky = prelozit(repliky, ant, rody)

    # prekladatel smi vratit prazdny retezec u repliky, ktera nic nenese
    pred_filtrem = len(cesky)
    cesky = [(m, t) for m, t in cesky if t and t.strip()]
    if len(cesky) < pred_filtrem:
        print(f"  vypuštěno {pred_filtrem - len(cesky)} prázdných replik")
    cesky = slouc_navazujici(cesky)

    if not args.bez_korektury:
        print("\nKorektura...")
        cesky = zkorektorovat(cesky, ant, rody)

    cesky = sjednot_uvod(cesky)

    print("\nNamlouvám...")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        skupiny = []
        for i, (mluvci, text) in enumerate(cesky):
            skupiny.append(namluv(text, obsazeni[mluvci], goo, tmp, i))
            print(f"  {i + 1}/{len(cesky)}")

        print("\nSlepuji a vyrovnávám hlasitost...")
        slep(skupiny, Path(args.vystup), tmp)

    # ulozime i cesky prepis, hodi se ke kontrole
    txt = Path(args.vystup).with_suffix(".txt")
    txt.write_text(
        "\n\n".join(f"[{m}] {t}" for m, t in cesky), encoding="utf-8"
    )

    print(f"\nHotovo: {args.vystup}")
    print(f"Český přepis: {txt}")


if __name__ == "__main__":
    main()
