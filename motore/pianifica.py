#!/usr/bin/env python3
"""
Decide cosa scaricare, in base all'ora di New York.

Non tutte le corse devono fare tutto: prima dell'apertura ha senso solo il
pre-mercato, dopo la chiusura solo i prezzi di chiusura. Fare tutto sempre
significherebbe raddoppiare le richieste per dati che a quell'ora non
esistono ancora (o non cambiano piu').

Il ragionamento in chiaro:

    prima delle 9:30 a New York   ->  pre-mercato   (la chiusura e' di ieri,
                                      e l'abbiamo gia' presa ieri sera)
    fra le 9:30 e le 16:00        ->  chiusura, con i prezzi riscaricati:
                                      e' seduta, i prezzi si muovono
    dopo le 16:00                 ->  chiusura, riscaricata: e' il dato buono
    fine settimana                ->  niente di nuovo da prendere

Una volta a settimana la corsa serale ricalcola anche l'universo: chi sono i
150 piu' scambiati cambia lentamente, e ricalcolarlo ogni volta vorrebbe dire
330 richieste in piu' per una lista quasi identica.

Scrive le decisioni dove il workflow le legge (GITHUB_OUTPUT). Lanciandolo a
mano stampa e basta, cosi' si puo' verificare cosa farebbe adesso.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:                                    # non dovrebbe succedere
    NY = timezone(timedelta(hours=-4))


def eta_universo() -> float | None:
    """Da quanti giorni non si ricalcola la classifica di liquidita'."""
    p = ROOT / ".cache" / "universe"
    if not p.is_dir():
        return None
    file = list(p.glob("*.json"))
    if not file:
        return None
    piu_recente = max(f.stat().st_mtime for f in file)
    import time
    return (time.time() - piu_recente) / 86400.0


def decidi(ora_ny: datetime, manuale: str = "") -> dict:
    feriale = ora_ny.weekday() < 5
    minuti = ora_ny.hour * 60 + ora_ny.minute
    apertura, chiusura = 9 * 60 + 30, 16 * 60

    d = {"chiusura": "no", "premercato": "no", "opzioni_chiusura": "", "etichetta": ""}

    if manuale and manuale != "automatico":
        if manuale in ("chiusura", "tutto"):
            d["chiusura"] = "si"; d["opzioni_chiusura"] = "--refresh-quotes"
        if manuale in ("premercato", "tutto"):
            d["premercato"] = "si"
        if manuale == "universo":
            d["chiusura"] = "si"; d["opzioni_chiusura"] = "--refresh --refresh-quotes"
        d["etichetta"] = f"richiesta manuale: {manuale}"
        return d

    if not feriale:
        d["etichetta"] = "fine settimana: nessun dato nuovo, la pagina resta com'e'"
        return d

    if minuti < apertura:
        d["premercato"] = "si"
        d["etichetta"] = f"pre-mercato delle {ora_ny:%H:%M} a New York"
    elif minuti < chiusura:
        d["chiusura"] = "si"; d["opzioni_chiusura"] = "--refresh-quotes"
        d["etichetta"] = f"seduta in corso, prezzi delle {ora_ny:%H:%M} a New York"
    else:
        d["chiusura"] = "si"; d["opzioni_chiusura"] = "--refresh-quotes"
        d["etichetta"] = f"chiusura del {ora_ny:%d/%m}"
        eta = eta_universo()
        if eta is None or eta > 6:
            # una volta a settimana, di sera: e' la corsa lunga
            d["opzioni_chiusura"] = "--refresh --refresh-quotes"
            quanto = "mai calcolato" if eta is None else f"{eta:.0f} giorni"
            d["etichetta"] += f" + ricalcolo dell'universo ({quanto})"
    return d


def main() -> int:
    ora = datetime.now(NY)
    d = decidi(ora, os.environ.get("SCELTA_MANUALE", ""))

    print(f"Ora a New York : {ora:%A %d/%m/%Y %H:%M}")
    print(f"Decisione      : {d['etichetta']}")
    print(f"  chiusura     : {d['chiusura']} {d['opzioni_chiusura']}")
    print(f"  pre-mercato  : {d['premercato']}")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            for k, v in d.items():
                fh.write(f"{k}={v}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
