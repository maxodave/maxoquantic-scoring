"""
Lettura e scrittura dei pesi in config/scoring.yml, senza rovinare il file.

Il problema: caricare uno YAML con una libreria e riscriverlo cancella tutti i
commenti. In `scoring.yml` i commenti sono metà del valore del file — spiegano
perché un peso è quello che è. Un pannello che li cancella al primo salvataggio
è un pannello che peggiora il progetto.

Quindi qui non si riscrive il file: si modificano le singole righe dei pesi,
riga per riga, lasciando intatto tutto il resto — commenti, ordine, spaziatura,
righe commentate. Un peso nuovo viene aggiunto in fondo al blocco; un peso
rimosso viene commentato, non cancellato, così la storia del file resta leggibile.
"""
from __future__ import annotations

import re
from pathlib import Path

# `  ev_ebitda:        0.14`   oppure   `  # roic:           0.13`
RIGA_PESO = re.compile(r"^(?P<ind>\s+)(?P<cmt>#\s*)?(?P<key>[a-z_][a-z0-9_]*)\s*:\s*"
                       r"(?P<val>-?\d+(?:\.\d+)?)\s*(?P<coda>#.*)?$")


def _leggi(p: Path) -> str:
    """
    newline="" e' obbligatorio: senza, Python traduce i CRLF in LF durante la
    lettura, il salvataggio non si accorge che il file era in stile Windows e
    lo riscrive tutto con le terminazioni sbagliate — un diff di 100 righe per
    aver cambiato un numero. (Path.read_text non accetta `newline` prima di
    Python 3.13, quindi si usa open().)
    """
    with p.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _trova_blocco(righe: list[str]) -> tuple[int, int, str]:
    """
    Individua il blocco dei pesi: (prima riga dentro, ultima+1, indentazione).
    Cerca `weights:` dentro `scoring:`, non un `weights:` qualunque.
    """
    i_scoring = None
    for i, r in enumerate(righe):
        if re.match(r"^scoring\s*:\s*(#.*)?$", r):
            i_scoring = i
            break
    if i_scoring is None:
        raise ValueError("in questo config non c'è una sezione `scoring:`")

    i_weights = None
    for i in range(i_scoring + 1, len(righe)):
        r = righe[i]
        if r.strip() and not r[0].isspace():   # inizio di un'altra sezione radice
            break
        if re.match(r"^\s+weights\s*:\s*(#.*)?$", r):
            i_weights = i
            break
    if i_weights is None:
        raise ValueError("in `scoring:` non c'è `weights:`")

    ind_w = len(righe[i_weights]) - len(righe[i_weights].lstrip())
    inizio = i_weights + 1
    fine = inizio
    ind_voci = " " * (ind_w + 2)
    for i in range(inizio, len(righe)):
        r = righe[i]
        if not r.strip():                       # riga vuota: può stare dentro il blocco
            fine = i + 1
            continue
        ind = len(r) - len(r.lstrip())
        if ind <= ind_w:                        # siamo usciti dal blocco
            break
        m = RIGA_PESO.match(r)
        if m:
            ind_voci = m.group("ind")
        fine = i + 1

    # le righe vuote finali non fanno parte del blocco
    while fine > inizio and not righe[fine - 1].strip():
        fine -= 1
    return inizio, fine, ind_voci


def read_weights(path: str | Path) -> dict[str, float]:
    """Solo i pesi ATTIVI (le righe commentate sono, appunto, disattivate)."""
    righe = _leggi(Path(path)).splitlines()
    inizio, fine, _ = _trova_blocco(righe)
    out: dict[str, float] = {}
    for r in righe[inizio:fine]:
        m = RIGA_PESO.match(r)
        if m and not m.group("cmt"):
            out[m.group("key")] = float(m.group("val"))
    return out


def write_weights(path: str | Path, pesi: dict[str, float],
                  valide: set[str] | None = None) -> dict[str, list[str]]:
    """
    Allinea il blocco dei pesi a `pesi`. Restituisce cosa è cambiato.
    `valide`: se passato, un peso su una chiave non compresa viene rifiutato
    (il pannello passa qui le chiavi del catalogo).
    """
    pesi = {k: float(v) for k, v in pesi.items()}
    if valide is not None:
        ignote = [k for k in pesi if k not in valide]
        if ignote:
            raise ValueError(f"metriche non nel catalogo: {sorted(ignote)}")
    negativi = [k for k, v in pesi.items() if v < 0]
    if negativi:
        raise ValueError(f"pesi negativi non ammessi: {sorted(negativi)} "
                         "(la direzione la decide il catalogo, non il segno)")

    p = Path(path)
    testo = _leggi(p)
    fine_riga = "\r\n" if "\r\n" in testo else "\n"
    righe = testo.splitlines()
    inizio, fine, ind = _trova_blocco(righe)

    diario: dict[str, list[str]] = {"modificati": [], "aggiunti": [], "disattivati": [], "invariati": []}
    nuove: list[str] = []
    visti: set[str] = set()

    for r in righe[inizio:fine]:
        m = RIGA_PESO.match(r)
        if not m:
            nuove.append(r)                     # commento libero: intatto
            continue
        key = m.group("key")
        coda = (" " + m.group("coda")) if m.group("coda") else ""
        attivo = not m.group("cmt")

        if key in pesi:
            visti.add(key)
            nuovo = _fmt(m.group("ind"), key, pesi[key], coda)
            if attivo and float(m.group("val")) == pesi[key]:
                diario["invariati"].append(key)
                nuove.append(r)
            else:
                diario["modificati" if attivo else "aggiunti"].append(key)
                nuove.append(nuovo)
        elif attivo:
            # non è più fra i pesi: si commenta, non si cancella
            diario["disattivati"].append(key)
            nuove.append(f"{m.group('ind')}# {key}: {m.group('val')}{coda}")
        else:
            nuove.append(r)                     # già commentato: lasciato com'è

    for key, val in pesi.items():
        if key not in visti:
            diario["aggiunti"].append(key)
            nuove.append(_fmt(ind, key, val, ""))

    fuori = righe[:inizio] + nuove + righe[fine:]
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        fh.write(fine_riga.join(fuori) + fine_riga)
    tmp.replace(p)                              # scrittura atomica
    return diario


def _fmt(ind: str, key: str, val: float, coda: str) -> str:
    v = f"{val:g}"
    return f"{ind}{key}:{' ' * max(1, 17 - len(key))}{v}{coda}"
