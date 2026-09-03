#!/usr/bin/env python3
"""
Rimette i dati della pagina pubblicata dentro site/, prima di aggiornarli.

Serve perche' ogni corsa su GitHub parte da una macchina pulita: se quella
delle 8 del mattino aggiorna solo il pre-mercato e i dati di chiusura non ci
sono, la pagina ricostruita perderebbe meta' di se stessa.

La soluzione e' che lo stato non sta da nessun'altra parte: **e' la pagina
pubblicata**. index.html contiene entrambi gli insiemi di dati, quindi si
rileggono da li' e si riscrivono come file, poi la corsa aggiorna solo la
parte che le compete. Nessun file di appoggio da tenere sincronizzato, e la
cosa si ripara da sola: se index.html e' buono, lo stato e' buono.

    python3 ripristina_dati.py                 legge ../index.html
    python3 ripristina_dati.py -i altra.html
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARCATORE = re.compile(r"window\.__DATI__\s*=\s*(\{.*?\});\s*\n", re.S)

NOMI = {"chiusura": "data.json", "premarket": "data-premarket.json"}


def estrai(html: str) -> dict:
    m = MARCATORE.search(html)
    if not m:
        raise SystemExit("Nella pagina non c'e' nessun blocco window.__DATI__: "
                         "non e' una pagina autonoma.")
    # Il generatore protegge le sequenze "</" scrivendole "<\/": qui si torna
    # indietro, altrimenti il JSON non e' valido.
    return json.loads(m.group(1).replace("<\\/", "</"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ripristina site/*.json dalla pagina pubblicata")
    ap.add_argument("-i", "--input", default=str(ROOT.parent / "index.html"))
    a = ap.parse_args(argv)

    p = Path(a.input)
    if not p.exists():
        print(f"{p} non esiste: si riparte da zero, la corsa scarichera' tutto.")
        return 0

    dati = estrai(p.read_text(encoding="utf-8"))
    (ROOT / "site").mkdir(parents=True, exist_ok=True)
    for chiave, nome in NOMI.items():
        blocco = dati.get(chiave)
        if not blocco:
            print(f"  {chiave:<10} assente nella pagina")
            continue
        (ROOT / "site" / nome).write_text(
            json.dumps(blocco, ensure_ascii=False, indent=1), encoding="utf-8")
        ses = (blocco.get("meta") or {}).get("sessione") or {}
        print(f"  {chiave:<10} {len(blocco.get('rows', []))} titoli, "
              f"seduta {ses.get('data', '?')} -> site/{nome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
