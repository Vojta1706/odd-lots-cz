#!/usr/bin/env python3
"""feed.py - udrzuje RSS feed s hotovymi ceskymi epizodami.

Feed lezi v docs/<TOKEN>/feed.xml a servíruje ho GitHub Pages.
Seznam epizod se drzi v docs/<TOKEN>/epizody.json, feed se z nej pokazde
vygeneruje cely znovu - je to jednodussi a spolehlivejsi nez XML upravovat.

    python cloud/feed.py --pridej vystup/<slug>_cz.json --zaklad <adresa MP3>
    python cloud/feed.py --pregeneruj
"""
import argparse
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

KOREN = Path(__file__).resolve().parent.parent
NASTAVENI = json.loads((KOREN / "cloud" / "nastaveni.json").read_text(encoding="utf-8"))

TOKEN = NASTAVENI["token"]
DOCS = KOREN / "docs" / TOKEN
SEZNAM = DOCS / "epizody.json"
FEED = DOCS / "feed.xml"


def nacti_seznam():
    if SEZNAM.exists():
        return json.loads(SEZNAM.read_text(encoding="utf-8"))
    return []


def uloz_seznam(polozky):
    DOCS.mkdir(parents=True, exist_ok=True)
    SEZNAM.write_text(json.dumps(polozky, ensure_ascii=False, indent=2),
                      encoding="utf-8")


def vygeneruj(polozky):
    """Z seznamu epizod slozi RSS feed pro podcastove aplikace."""
    hlavni = NASTAVENI["feed"]
    zaklad = NASTAVENI["adresa_webu"].rstrip("/") + "/" + TOKEN

    kusy = []
    for e in polozky:
        delka = int(e.get("delka_s", 0))
        cas = f"{delka // 3600:02d}:{delka % 3600 // 60:02d}:{delka % 60:02d}"
        kusy.append(f"""    <item>
      <title>{escape(e['nazev'])}</title>
      <description>{escape(e.get('popis', ''))}</description>
      <link>{escape(e.get('zdroj', ''))}</link>
      <guid isPermaLink="false">{escape(e['slug'])}</guid>
      <pubDate>{escape(e['vytvoreno'])}</pubDate>
      <enclosure url="{escape(e['mp3_url'])}" length="{e['velikost']}" type="audio/mpeg"/>
      <itunes:duration>{cas}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
    </item>""")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(hlavni['nazev'])}</title>
    <description>{escape(hlavni['popis'])}</description>
    <link>{escape(zaklad)}/</link>
    <language>cs</language>
    <atom:link href="{escape(zaklad)}/feed.xml" rel="self" type="application/rss+xml"/>
    <itunes:author>{escape(hlavni['autor'])}</itunes:author>
    <itunes:explicit>false</itunes:explicit>
    <itunes:block>Yes</itunes:block>
{chr(10).join(kusy)}
  </channel>
</rss>
"""


def delka_mp3(cesta):
    """Delka nahravky v sekundach pres ffprobe. Kdyz se nepovede, vrati 0."""
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(cesta)],
            capture_output=True, text=True, timeout=60,
        )
        return int(float(r.stdout.strip()))
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser(description="Údržba RSS feedu s českými epizodami.")
    ap.add_argument("--pridej", help="cesta k <slug>_cz.json z vystup/")
    ap.add_argument("--mp3", help="cesta k MP3 (kvůli zjištění délky)")
    ap.add_argument("--mp3-url", help="veřejná adresa, kde MP3 leží")
    ap.add_argument("--pregeneruj", action="store_true",
                    help="jen znovu vytvořit feed.xml ze seznamu")
    args = ap.parse_args()

    polozky = nacti_seznam()

    if args.pridej:
        nova = json.loads(Path(args.pridej).read_text(encoding="utf-8"))
        if not args.mp3_url:
            raise SystemExit("Chybí --mp3-url.")
        nova["mp3_url"] = args.mp3_url
        nova["delka_s"] = delka_mp3(args.mp3) if args.mp3 else 0

        # stejny slug uz ve feedu byt muze - nahradime ho, nezdvojujeme
        polozky = [x for x in polozky if x["slug"] != nova["slug"]]
        polozky.insert(0, nova)
        uloz_seznam(polozky)
        print(f"Přidáno do feedu: {nova['nazev']}")

    DOCS.mkdir(parents=True, exist_ok=True)
    FEED.write_text(vygeneruj(polozky), encoding="utf-8")
    (DOCS.parent / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Feed má {len(polozky)} epizod: {FEED.relative_to(KOREN)}")


if __name__ == "__main__":
    main()
