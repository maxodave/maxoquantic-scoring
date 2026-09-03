"""
Il motore di scoring.

Contratto: score(rows, config) -> rows arricchite con
    _scores  : punteggio 0-1 per singola metrica
    score    : 0-100 (media pesata dei punteggi disponibili)
    coverage : quota di peso effettivamente coperta dai dati

Tre scelte di progetto, tutte reversibili da config/scoring.yml:

1. PERCENTILE, NON VALORE ASSOLUTO.
   Un P/E di 12 non è "buono" in senso assoluto: è buono rispetto a qualcosa.
   Il motore confronta ogni titolo con i suoi pari e usa il rango.
   Conseguenza da tenere presente: cambiando universo cambiano tutti i punteggi.

2. CONFRONTO DENTRO IL SETTORE (peer_group: sector).
   Il P/E medio delle utility e quello del software non sono confrontabili.
   Se un settore ha meno di `min_peers` titoli, si ricade sull'universo intero
   per non produrre percentili basati su tre osservazioni.

3. I DATI MANCANTI NON VALGONO ZERO.
   Un buco redistribuisce il suo peso sulle metriche presenti e abbassa la
   copertura. Sotto `min_coverage` la riga viene marcata inaffidabile.
   Trattare i buchi come zeri è il modo più rapido di produrre una classifica
   che premia le aziende con meno dati pubblicati.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from .metrics import BY_KEY, SCOREABLE
from .normalize import band_scores, percentile_scores, zscore_scores

Row = dict[str, Any]


# --------------------------------------------------------------------------- derivate
def add_derived(rows: list[Row]) -> list[Row]:
    """Calcola le metriche derivate. Idempotente, non sovrascrive valori già presenti."""
    for r in rows:
        price = _num(r.get("price"))
        vol = _num(r.get("volume"))
        avg = _num(r.get("avg_volume_3m"))
        mcap = _num(r.get("market_cap"))
        fcf = _num(r.get("fcf"))

        # Le chiavi vengono SEMPRE scritte, anche a None: una derivata assente
        # deve essere un buco dichiarato, non una chiave che non esiste.
        if r.get("dollar_volume") is None:
            r["dollar_volume"] = price * vol if (price is not None and vol is not None) else None
        if r.get("rel_volume") is None:
            r["rel_volume"] = vol / avg if (vol is not None and avg not in (None, 0)) else None
        if r.get("fcf_yield") is None:
            r["fcf_yield"] = fcf / mcap if (fcf is not None and mcap not in (None, 0)) else None
        if r.get("week52_position") is None:
            lo, hi = _num(r.get("week52_low")), _num(r.get("week52_high"))
            r["week52_position"] = ((price - lo) / (hi - lo)
                                    if (price is not None and lo is not None
                                        and hi is not None and hi > lo) else None)
        if r.get("change_abs") is None:
            # prezzo - chiusura precedente, ricavato dalla percentuale:
            #   p = (P - C)/C   =>   P - C = P * p / (1 + p)
            chg = _num(r.get("change_pct"))
            r["change_abs"] = (price * chg / (1 + chg)
                               if (price is not None and chg is not None and chg != -1) else None)
    return rows


# --------------------------------------------------------------------------- filtri
def apply_filters(rows: list[Row], f: dict) -> tuple[list[Row], dict[str, int]]:
    """
    L'equivalente degli "Equity Filters" di Yahoo, ma dichiarato ed esplicito.
    Restituisce (righe superstiti, quante righe ha scartato ciascun filtro).
    Il secondo valore serve a non ritrovarsi mai con una lista filtrata
    senza sapere da cosa: è esattamente il problema della pagina Most Actives.
    """
    dropped: dict[str, int] = defaultdict(int)
    out = []
    for r in rows:
        why = None
        if (v := f.get("min_price")) is not None and _lt(r.get("price"), v):
            why = f"min_price<{v}"
        elif (v := f.get("max_price")) is not None and _gt(r.get("price"), v):
            why = f"max_price>{v}"
        elif (v := f.get("min_market_cap")) is not None and _lt(r.get("market_cap"), v):
            why = f"min_market_cap<{v}"
        elif (v := f.get("min_dollar_volume")) is not None and _lt(r.get("dollar_volume"), v):
            why = f"min_dollar_volume<{v}"
        elif (v := f.get("min_avg_volume")) is not None and _lt(r.get("avg_volume_3m"), v):
            why = f"min_avg_volume<{v}"
        elif (v := f.get("exclude_sectors")) and r.get("sector") in set(v):
            why = "exclude_sectors"
        elif (v := f.get("only_sectors")) and r.get("sector") not in set(v):
            why = "only_sectors"
        if why:
            dropped[why] += 1
        else:
            out.append(r)
    return out, dict(dropped)


# --------------------------------------------------------------------------- scoring
def score(rows: list[Row], config: dict) -> dict:
    weights: dict[str, float] = {
        k: float(v) for k, v in (config.get("scoring", {}).get("weights") or {}).items()
        if float(v) != 0
    }
    if not weights:
        raise ValueError(
            "Nessun peso definito. Compila scoring.weights in config/scoring.yml: "
            "senza pesi non esiste un punteggio, solo una tabella."
        )
    unknown = [k for k in weights if k not in BY_KEY]
    if unknown:
        raise ValueError(f"Metriche non nel catalogo (engine/metrics.py): {unknown}")

    # Controllo fatto sui DATI, non sulla configurazione: un peso su una metrica
    # vuota per tutte le righe sparisce in silenzio dal punteggio e fa scendere
    # la copertura senza spiegazione. Vale per qualunque provider.
    # (calcolato piu' sotto, dopo add_derived: le derivate esistono solo dopo)

    norm = config.get("normalization", {}) or {}
    method = norm.get("method", "percentile")
    peer_group = norm.get("peer_group", "sector")
    min_peers = int(norm.get("min_peers", 8))
    min_cov = float(config.get("scoring", {}).get("min_coverage", 0.5))

    add_derived(rows)

    empty = [k for k in weights
             if all(r.get(k) is None for r in rows)] if rows else list(weights)

    # gruppi di confronto
    groups: dict[Any, list[int]] = defaultdict(list)
    if peer_group == "sector":
        for i, r in enumerate(rows):
            groups[r.get("sector") or "__none__"].append(i)
        small = [g for g, idxs in groups.items() if len(idxs) < min_peers]
        if small:
            fallback = [i for g in small for i in groups[g]]
            for g in small:
                del groups[g]
            groups["__universe_fallback__"] = fallback
    else:
        groups["__all__"] = list(range(len(rows)))

    for r in rows:
        r["_scores"] = {}

    # QUALI METRICHE NORMALIZZARE.
    # Non solo quelle pesate: tutte le punteggiabili che hanno almeno un dato.
    # Costa poco (e' un ordinamento per metrica) e serve al ricalcolo dei pesi
    # IN DIRETTA nel sito: la pagina puo' rifare il punteggio con pesi diversi
    # senza riscaricare niente, perche' i percentili ci sono gia'.
    # Il punteggio e la copertura ufficiali restano calcolati SOLO sui pesi
    # del config: il ricalcolo nel browser e' una simulazione, non il dato.
    norm_keys = list(dict.fromkeys(
        list(weights)
        + [k for k in SCOREABLE if any(r.get(k) is not None for r in rows)]
    ))

    # normalizzazione metrica per metrica, gruppo per gruppo
    for key in norm_keys:
        m = BY_KEY[key]
        for idxs in groups.values():
            vals = [rows[i].get(key) for i in idxs]
            if m.direction == "target_band" and m.band:
                s = band_scores(vals, tuple(m.band))
            elif method == "zscore":
                s = zscore_scores(vals, m.winsor)
                if m.direction == "lower_better":
                    s = [None if x is None else 1.0 - x for x in s]
            else:
                s = percentile_scores(vals, m.winsor)
                if m.direction == "lower_better":
                    s = [None if x is None else 1.0 - x for x in s]
            for pos, i in enumerate(idxs):
                rows[i]["_scores"][key] = s[pos]

    total_w = sum(weights.values())
    for r in rows:
        num = 0.0
        wsum = 0.0
        for key, w in weights.items():
            s = r["_scores"].get(key)
            if s is None:
                continue
            num += w * s
            wsum += w
        r["coverage"] = round(wsum / total_w, 4) if total_w else 0.0
        r["score"] = round(100.0 * num / wsum, 2) if wsum > 0 else None
        r["reliable"] = bool(r["coverage"] >= min_cov and r["score"] is not None)

    ranked = sorted(
        rows,
        key=lambda r: (r["reliable"], r["score"] if r["score"] is not None else -1),
        reverse=True,
    )
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    return {
        "rows": ranked,
        "meta": {
            "weights": weights,
            "scored_keys": norm_keys,
            "method": method,
            "peer_group": peer_group,
            "min_peers": min_peers,
            "min_coverage": min_cov,
            "peer_groups": {str(g): len(i) for g, i in groups.items()},
            "n": len(ranked),
            "n_reliable": sum(1 for r in ranked if r["reliable"]),
            "empty_weights": empty,
        },
    }


def explain(row: Row, weights: dict[str, float]) -> list[dict]:
    """Scomposizione del punteggio di una riga: quanto ha contribuito ogni metrica."""
    total_w = sum(w for k, w in weights.items() if row["_scores"].get(k) is not None) or 1.0
    out = []
    for k, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        s = row["_scores"].get(k)
        out.append({
            "metric": k,
            "label": BY_KEY[k].label,
            "raw": row.get(k),
            "score01": None if s is None else round(s, 4),
            "weight": w,
            "contribution_pts": None if s is None else round(100.0 * w * s / total_w, 2),
            "missing": s is None,
        })
    return out


# --------------------------------------------------------------------------- util
def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _lt(v, thr) -> bool:
    n = _num(v)
    return n is None or n < thr


def _gt(v, thr) -> bool:
    n = _num(v)
    return n is not None and n > thr
