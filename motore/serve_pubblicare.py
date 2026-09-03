#!/usr/bin/env python3
"""
Dice se la pagina appena costruita merita di essere pubblicata.

Il confronto byte a byte non basta. Ogni corsa riscrive `generated_at` —
l'ora in cui il motore ha girato — anche quando ogni singolo numero e'
arrivato dalla cache e non e' cambiato niente. Confrontando i file interi,
quel campo da solo faceva pubblicare quattro volte al giorno: quattro commit
e quattro ricostruzioni del sito per un orologio che avanza.

Qui si confronta cio' che un lettore vedrebbe davvero: i titoli, i numeri, la
seduta. Se sono identici non si pubblica, e la pagina online continua a
dichiarare l'ora in cui quei dati sono stati calcolati per davvero — che e'
piu' onesto di un'ora che si aggiorna senza che i dati cambino.

    python3 serve_pubblicare.py --nuova ../index.html --vecchia <(git show HEAD:index.html)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ripristina_dati import estrai            # noqa: E402


def confrontabile(dati: dict) -> dict:
    """Gli stessi dati, senza i campi che cambiano da soli a ogni corsa."""
    pulito = {}
    for chiave, blocco in (dati or {}).items():
        b = dict(blocco)
        b.pop("generated_at", None)
        meta = dict(b.get("meta") or {})
        meta.pop("generated_at", None)
        b["meta"] = meta
        pulito[chiave] = b
    return pulito


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Confronta i dati, non l'orologio")
    ap.add_argument("--nuova", required=True)
    ap.add_argument("--vecchia", required=True)
    a = ap.parse_args(argv)

    nuova = Path(a.nuova)
    vecchia = Path(a.vecchia)
    if not nuova.exists():
        print("La pagina nuova non esiste."); return 1

    dn = confrontabile(estrai(nuova.read_text(encoding="utf-8")))
    if not vecchia.exists():
        esito, perche = "si", "non c'era ancora una pagina pubblicata"
    else:
        try:
            dv = confrontabile(estrai(vecchia.read_text(encoding="utf-8")))
        except SystemExit:
            dv = None
        if dv is None:
            esito, perche = "si", "la pagina pubblicata non conteneva dati leggibili"
        elif json.dumps(dn, sort_keys=True) == json.dumps(dv, sort_keys=True):
            esito, perche = "no", "gli stessi identici dati sono gia' online"
        else:
            cambiate = [k for k in dn
                        if json.dumps(dn.get(k), sort_keys=True) != json.dumps(dv.get(k), sort_keys=True)]
            esito, perche = "si", "dati nuovi in: " + ", ".join(cambiate)

    print(f"pubblicare: {esito} — {perche}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"pubblicare={esito}\nperche={perche}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
