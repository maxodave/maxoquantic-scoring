"""
Normalizzazione: da valori grezzi non confrontabili a punteggi 0-1.

Il problema che risolve: P/E 18, ROE 0.22, FCF 3.4e9 e Debt/Equity 145 non si
possono sommare. Vanno prima portati sulla stessa scala, e la scala deve essere
robusta agli outlier, perché nei dati finanziari gli outlier sono la norma
(crescita utili +2000% da base minuscola, P/E 900, ROE su equity negativo).

Nessuna dipendenza esterna: solo standard library.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

Number = Optional[float]


def _clean(values: Iterable[Number]) -> list[float]:
    out = []
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
            continue
        out.append(f)
    return out


def quantile(sorted_vals: Sequence[float], q: float) -> float:
    """Quantile con interpolazione lineare. sorted_vals deve essere ordinato."""
    if not sorted_vals:
        raise ValueError("serie vuota")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def winsorize_bounds(values: Iterable[Number], lo_q: float, hi_q: float) -> tuple[float, float]:
    vals = sorted(_clean(values))
    if not vals:
        return (0.0, 0.0)
    return (quantile(vals, lo_q), quantile(vals, hi_q))


def clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def percentile_scores(values: Sequence[Number], winsor: tuple[float, float] = (0.02, 0.98)) -> list[Number]:
    """
    Rango percentile in [0,1], 'higher = 1'.
    Metodo: media dei ranghi per i pari merito, calcolato sui valori winsorizzati.
    I None restano None (non diventano zero: uno zero è un giudizio, un None è un buco).
    """
    lo, hi = winsorize_bounds(values, *winsor)
    idx_val = [(i, float(v)) for i, v in enumerate(values) if v is not None and _is_finite(v)]
    if not idx_val:
        return [None] * len(values)
    clipped = [(i, clip(v, lo, hi)) for i, v in idx_val]
    n = len(clipped)
    if n == 1:
        out: list[Number] = [None] * len(values)
        out[clipped[0][0]] = 0.5
        return out

    order = sorted(clipped, key=lambda t: t[1])
    ranks: dict[int, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and order[j + 1][1] == order[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0            # 0-based, media dei pari merito
        for k in range(i, j + 1):
            ranks[order[k][0]] = avg_rank / (n - 1)
        i = j + 1

    out = [None] * len(values)
    for i, r in ranks.items():
        out[i] = r
    return out


def zscore_scores(values: Sequence[Number], winsor: tuple[float, float] = (0.02, 0.98)) -> list[Number]:
    """Z-score winsorizzato, schiacciato in [0,1] con una logistica (z=+-2 -> ~0.12/0.88)."""
    import math

    lo, hi = winsorize_bounds(values, *winsor)
    vals = [clip(float(v), lo, hi) for v in values if v is not None and _is_finite(v)]
    if len(vals) < 2:
        return [0.5 if (v is not None and _is_finite(v)) else None for v in values]
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    sd = var ** 0.5
    out: list[Number] = []
    for v in values:
        if v is None or not _is_finite(v):
            out.append(None)
            continue
        z = 0.0 if sd == 0 else (clip(float(v), lo, hi) - mean) / sd
        out.append(1.0 / (1.0 + math.exp(-z)))
    return out


def band_scores(values: Sequence[Number], band: tuple[float, float]) -> list[Number]:
    """
    Punteggio per metriche con fascia ottimale (es. Current Ratio 1.2-3.0).
    Dentro la fascia -> 1.0. Fuori -> decade linearmente fino a 0 a una larghezza
    di fascia di distanza. Non è un percentile: è un giudizio assoluto,
    quindi NON dipende dall'universo.
    """
    lo, hi = band
    width = max(hi - lo, 1e-9)
    out: list[Number] = []
    for v in values:
        if v is None or not _is_finite(v):
            out.append(None)
            continue
        f = float(v)
        if lo <= f <= hi:
            out.append(1.0)
        elif f < lo:
            out.append(clip(1.0 - (lo - f) / width, 0.0, 1.0))
        else:
            out.append(clip(1.0 - (f - hi) / width, 0.0, 1.0))
    return out


def _is_finite(v) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))
