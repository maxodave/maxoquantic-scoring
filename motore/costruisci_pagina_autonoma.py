#!/usr/bin/env python3
"""
Costruisce UN SOLO file HTML con i dati dentro.

A cosa serve: la pagina normale (site/screener.html) legge data.json con una
richiesta, quindi ha bisogno di un server. Questa versione si porta i dati
appresso e si apre ovunque — da un telefono, da una chiavetta, da GitHub
Pages, anche senza rete.

Cosa NON fa, di proposito:
  - non esegue comandi: nessun server dietro, quindi i pulsanti restano spenti
    e la pagina lo dichiara. E' una fotografia, non lo strumento di lavoro;
  - non si aggiorna da sola: la si rigenera lanciando di nuovo questo script.

    python3 costruisci_pagina_autonoma.py                 -> pubblica/index.html
    python3 costruisci_pagina_autonoma.py -o /tmp/x.html
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def costruisci(sorgente: Path, dati: dict[str, Path], out: Path) -> Path:
    html = sorgente.read_text(encoding="utf-8")

    incorporati = {}
    for nome, percorso in dati.items():
        if not percorso.exists():
            print(f"  manca {percorso.name}: la sezione «{nome}» non sara' disponibile")
            continue
        incorporati[nome] = json.loads(percorso.read_text(encoding="utf-8"))
        print(f"  {nome:<10} {len(incorporati[nome].get('rows', []))} titoli "
              f"da {percorso.name}")
    if not incorporati:
        raise SystemExit("Nessun dato da incorporare: lancia prima `run.py update`.")

    # </script> dentro una stringa JSON chiuderebbe il tag che la contiene:
    # e' l'unico carattere che va protetto.
    blob = json.dumps(incorporati, ensure_ascii=False).replace("</", "<\\/")
    quando = datetime.now(timezone.utc).isoformat(timespec="seconds")

    inserto = (
        "<script>\n"
        f"/* Pagina autonoma generata il {quando}.\n"
        "   I dati sono qui dentro: nessuna richiesta di rete, nessun server.\n"
        "   Si rigenera con costruisci_pagina_autonoma.py */\n"
        f"window.__DATI__ = {blob};\n"
        "</script>\n"
    )
    if "</head>" not in html:
        raise SystemExit("La pagina sorgente non ha un </head>: non so dove mettere i dati.")
    html = html.replace("</head>", inserto + "</head>", 1)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Un solo file HTML, con i dati dentro")
    ap.add_argument("-o", "--out", default=str(ROOT / "pubblica" / "index.html"))
    a = ap.parse_args(argv)

    print("Incorporo i dati nella pagina:")
    out = costruisci(
        ROOT / "site" / "screener.html",
        {"chiusura": ROOT / "site" / "data.json",
         "premarket": ROOT / "site" / "data-premarket.json"},
        Path(a.out),
    )
    kb = out.stat().st_size / 1024
    print(f"\nscritto: {out}  ({kb:.0f} KB)")
    print("Doppio clic e funziona, anche senza rete. I comandi restano spenti:")
    print("non c'e' nessun pannello dietro una pagina che sta su un sito.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
