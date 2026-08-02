#!/usr/bin/env python3
"""obal.py - vyrobi ctvercovy obal podcastu do docs/<token>/obal.jpg.

Podcastove aplikace chteji ctverec 1400-3000 px, JPEG nebo PNG, v RGB.
Vlastni obrazek: hod ho do slozky projektu jako 'muj-obal.jpg' a pust
    python cloud/obal.py muj-obal.jpg
Skript ho jen ostrihne na ctverec a ulozi ve spravne velikosti.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

KOREN = Path(__file__).resolve().parent.parent
NASTAVENI = json.loads((KOREN / "cloud" / "nastaveni.json").read_text(encoding="utf-8"))
CIL = KOREN / "docs" / NASTAVENI["token"] / NASTAVENI["feed"].get("obal", "obal.jpg")

STRANA = 1500
POZADI = (24, 34, 48)        # tmave modrosede
TEXT = (238, 240, 243)
DOPLNEK = (110, 168, 214)    # svetle modra


def pismo(velikost, tucne=True):
    for jmeno in (("seguibl.ttf", "segoeuib.ttf") if tucne else ("segoeui.ttf",)):
        cesta = Path("C:/Windows/Fonts") / jmeno
        if cesta.exists():
            return ImageFont.truetype(str(cesta), velikost)
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if tucne else "DejaVuSans.ttf",
                                  velikost)
    except OSError:
        return ImageFont.load_default()


def na_stred(kresba, text, font, y, barva):
    l, t, r, b = kresba.textbbox((0, 0), text, font=font)
    kresba.text(((STRANA - (r - l)) / 2 - l, y), text, font=font, fill=barva)
    return b - t


def vyrob():
    obr = Image.new("RGB", (STRANA, STRANA), POZADI)
    k = ImageDraw.Draw(obr)

    # jemny pruh nahore i dole, at to neni jen plocha barva
    k.rectangle([0, 0, STRANA, 18], fill=DOPLNEK)
    k.rectangle([0, STRANA - 18, STRANA, STRANA], fill=DOPLNEK)

    nazev = NASTAVENI["feed"]["nazev"]
    casti = nazev.rsplit(" ", 1)
    horni = casti[0] if len(casti) > 1 else nazev
    dolni = casti[1] if len(casti) > 1 else ""

    na_stred(k, horni.upper(), pismo(150), 520, TEXT)
    if dolni:
        na_stred(k, dolni.lower(), pismo(210), 700, DOPLNEK)

    k.line([(STRANA * 0.3, 990), (STRANA * 0.7, 990)], fill=DOPLNEK, width=4)
    na_stred(k, "strojový překlad a namluvení", pismo(52, tucne=False), 1040, (150, 160, 172))

    return obr


def z_vlastniho(cesta):
    obr = Image.open(cesta).convert("RGB")
    s = min(obr.size)
    x = (obr.width - s) // 2
    y = (obr.height - s) // 2
    return obr.crop((x, y, x + s, y + s)).resize((STRANA, STRANA), Image.LANCZOS)


def main():
    obr = z_vlastniho(sys.argv[1]) if len(sys.argv) > 1 else vyrob()
    CIL.parent.mkdir(parents=True, exist_ok=True)
    obr.save(CIL, "JPEG", quality=88, optimize=True)
    print(f"Obal uložen: {CIL.relative_to(KOREN)}")
    print(f"  {obr.width}x{obr.height} px, {CIL.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
