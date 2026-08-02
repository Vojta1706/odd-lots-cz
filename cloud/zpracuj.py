#!/usr/bin/env python3
"""zpracuj.py - obal kolem podcast_cz.py pro beh na GitHubu.

Vezme URL epizody z omny.fm, zjisti nazev a slug, pusti hlavni skript
a vedle MP3 ulozi i male JSON s udaji pro RSS feed.

Spousti se z workflow, ne rucne:
    python cloud/zpracuj.py "https://omny.fm/shows/odd-lots/nazev-epizody"
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

KOREN = Path(__file__).resolve().parent.parent
VYSTUP = KOREN / "vystup"

sys.path.insert(0, str(KOREN))
import podcast_cz as p


def zjisti_udaje(url):
    """Ze stranky epizody vytahne slug a lidsky nazev."""
    slug = url.rstrip("/").split("/")[-1].split("?")[0]

    try:
        r = p.requests.get(url, headers=p.PROHLIZEC, timeout=60)
        html = r.text if r.status_code == 200 else ""
    except Exception:
        html = ""

    nazev = slug.replace("-", " ").capitalize()
    m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if not m:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html)
    if m:
        nazev = (m.group(1)
                 .replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                 .split(" | ")[0].strip())

    popis = ""
    m = re.search(r'<meta property="og:description" content="([^"]*)"', html)
    if m:
        popis = m.group(1).replace("&amp;", "&").replace("&#39;", "'")[:600]

    return slug, nazev, popis


def main():
    if len(sys.argv) < 2 or not p.je_url(sys.argv[1]):
        sys.exit("Použití: python cloud/zpracuj.py <URL epizody z omny.fm>")

    url = sys.argv[1].strip()
    slug, nazev, popis = zjisti_udaje(url)
    print(f"Epizoda : {nazev}")
    print(f"Slug    : {slug}\n")

    VYSTUP.mkdir(exist_ok=True)
    mp3 = VYSTUP / f"{slug}_cz.mp3"

    vysledek = subprocess.run(
        [sys.executable, str(KOREN / "podcast_cz.py"), url,
         "--full", "--vystup", str(mp3)],
        cwd=str(KOREN),
    )
    if vysledek.returncode != 0:
        sys.exit(f"Zpracování epizody selhalo (kód {vysledek.returncode}).")
    if not mp3.exists():
        sys.exit("Skript doběhl, ale MP3 nevzniklo.")

    udaje = {
        "slug": slug,
        "nazev": nazev,
        "popis": popis,
        "zdroj": url,
        "soubor": mp3.name,
        "velikost": mp3.stat().st_size,
        "vytvoreno": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000"),
    }
    (VYSTUP / f"{slug}_cz.json").write_text(
        json.dumps(udaje, ensure_ascii=False, indent=2), encoding="utf-8")

    # workflow si tyhle hodnoty precte
    vystupy = os.environ.get("GITHUB_OUTPUT")
    if vystupy:
        with open(vystupy, "a", encoding="utf-8") as f:
            f.write(f"slug={slug}\n")
            f.write(f"nazev={nazev}\n")
            f.write(f"mp3={mp3}\n")

    print(f"\nHotovo: {mp3.name} ({mp3.stat().st_size / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
