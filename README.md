# Odd Lots česky

Soukromý nástroj, který z anglické epizody podcastu vyrobí českou zvukovou verzi:
stáhne přepis, srovná mluvčí, přeloží, zkorektoruje a namluví českými hlasy.

Hotové epizody se ukládají do Releases a přidávají do RSS feedu, který jde
přidat do podcastové aplikace.

## Jak pustit novou epizodu

1. Nahoře **Actions**
2. Vlevo **Zpracovat epizodu**
3. Vpravo **Run workflow**
4. Do pole vlož adresu epizody z omny.fm, například
   `https://omny.fm/shows/odd-lots/nazev-epizody`
5. **Run workflow**

Běh trvá zhruba 30–50 minut. Postup uvidíš v Actions, na konci se objeví
shrnutí s odkazem na MP3. Do podcastové aplikace se epizoda objeví po
stažení feedu dolů.

Funguje to i z mobilu — GitHub v prohlížeči i v aplikaci to má stejně.

## Co je kde

| Soubor | K čemu je |
|---|---|
| `podcast_cz.py` | hlavní skript: překlad, korektura, hlasy |
| `cloud/zpracuj.py` | obal pro běh na GitHubu |
| `cloud/feed.py` | údržba RSS feedu |
| `cloud/nastaveni.json` | adresa webu, token feedu, název podcastu |
| `.github/workflows/epizoda.yml` | ruční úloha |
| `docs/<token>/feed.xml` | výsledný feed |

## Klíče

Jsou uložené jako **Settings → Secrets and variables → Actions**:

- `ANTHROPIC_API_KEY` — překlad a korektura
- `GOOGLE_TTS_KEY` — namluvení

V kódu nejsou a ve výpisech běhu se nezobrazují.

## Cena

Jedna epizoda vyjde zhruba na **2 $** (překlad ~0,35 $, hlasy ~1,60 $).
Běh na GitHubu je zdarma.

## Ladění překladu

Kvalita stojí a padá na `PREKLAD_SYSTEM` a `KOREKTURA_SYSTEM` v `podcast_cz.py`.
Když něco ve výsledku zaskřípe, nejspolehlivěji to uzavřeš přidáním položky
do `SLOVNIK` — konkrétní chybný tvar zabírá líp než obecné pravidlo.
