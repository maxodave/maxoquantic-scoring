"""
Costruzione dell'universo: i N titoli più liquidi.

Qui sta la correzione dell'errore di Yahoo. La pagina Most Actives ordina per
numero di AZIONI scambiate, e per questo si riempie di penny stock: GoPro a
1,24 $ con 488 M di azioni muove ~0,6 mld $ e arriva prima di NVIDIA che con
87 M di azioni a 222 $ ne muove ~19 mld.

Il criterio qui è il DENARO scambiato: prezzo x volume. In due passaggi:

    1. BACINO   una lista di candidati, larga (300-500 titoli):
                  - dallo screener Yahoo, se risponde
                  - altrimenti da config/seed_universe.txt (lista fissa,
                    sempre disponibile, che si può modificare a mano)
    2. RANKING  si scaricano le quote del bacino, si ordina per prezzo x volume
                e si tagliano i primi N.

Il passaggio 2 non è opzionale: è quello che rende la classifica corretta.
Anche partendo dal bacino dello screener (ordinato per pezzi) il re-ranking
rimette le cose a posto.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from .cache import TTL, Cache


def read_seed(path: str | Path) -> list[str]:
    """Legge una lista di ticker da file di testo: uno per riga, # per i commenti."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"lista seed non trovata: {p}")
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        t = line.split("#", 1)[0].strip().upper()
        if t:
            out.append(t)
    return list(dict.fromkeys(out))


def rank_by_dollar_volume(rows: list[dict], top_n: int,
                          min_price: float = 0.0,
                          min_market_cap: float = 0.0) -> tuple[list[dict], dict]:
    """
    Ordina per denaro scambiato e taglia ai primi `top_n`.
    Restituisce (righe ordinate, diagnostica). Le righe senza prezzo o senza
    volume non possono essere classificate e vengono contate a parte: sono un
    buco di dati, non titoli poco liquidi.
    """
    ok, no_data, too_small = [], 0, 0
    for r in rows:
        price = _num(r.get("price"))
        vol = _num(r.get("volume")) or _num(r.get("avg_volume_3m"))
        if price is None or vol is None:
            no_data += 1
            continue
        if price < min_price or (min_market_cap and (_num(r.get("market_cap")) or 0) < min_market_cap):
            too_small += 1
            continue
        r["dollar_volume"] = price * vol
        ok.append(r)

    ok.sort(key=lambda r: r["dollar_volume"], reverse=True)
    kept = ok[:top_n]
    return kept, {
        "candidati": len(rows),
        "classificabili": len(ok),
        "senza_prezzo_o_volume": no_data,
        "sotto_le_soglie": too_small,
        "tenuti": len(kept),
        "taglio_dollar_volume": round(kept[-1]["dollar_volume"], 0) if kept else None,
    }


def build(cfg: dict, provider, cache: Optional[Cache] = None,
          log: Callable[[str], None] = print, refresh: bool = False) -> tuple[list[str], dict]:
    """
    Restituisce (lista di ticker, diagnostica).
    La lista viene messa in cache: la classifica di liquidità è stabile nel
    tempo, non serve ricalcolarla ogni sera. `refresh=True` la forza.
    """
    u = cfg.get("universe", {}) or {}
    top_n = int(u.get("top_n") or u.get("limit") or 150)
    cache = cache or Cache(cfg.get("cache", {}).get("dir", ".cache"),
                           enabled=bool(cfg.get("cache", {}).get("enabled", True)))
    ttl = 0 if refresh else float(cfg.get("cache", {}).get("ttl_universe", TTL["universe"]))

    key = f"top{top_n}_{u.get('source', 'auto')}"
    cached = cache.get("universe", key, ttl)
    if cached:
        age_h = (cache.age("universe", key) or 0) / 3600
        log(f"universo   : {len(cached['tickers'])} titoli dalla cache "
            f"(aggiornata {age_h:.1f} h fa; `--refresh` per ricalcolarla)")
        return cached["tickers"], cached.get("diag", {})

    # ---------------------------------------------------------------- 1. bacino
    pool: list[str] = []
    source_used = ""
    seed_path = u.get("seed_path", "config/seed_universe.txt")

    source = u.get("source", "auto")

    if source in ("auto", "screener"):
        # Lo screener e' la via che vede tutto il mercato: la si prova sempre.
        try:
            pool = provider.universe({**cfg, "universe": {
                **u, "source": "screener",
                "limit": int(u.get("pool_size", 400)),
            }})
            source_used = "screener Yahoo"
        except Exception as e:
            log(f"             screener non disponibile ({type(e).__name__}), uso la lista seed")
        if not pool and source == "auto":
            pool = read_seed(seed_path)
            source_used = f"lista seed ({seed_path})"
    else:
        # source espliciti (tickers, file, ...): decide il provider
        pool = provider.universe(cfg)
        source_used = f"universe.source={source}"

    if not pool:
        raise RuntimeError(
            "Bacino vuoto: ne' lo screener ne' la fonte configurata hanno "
            "restituito ticker. Controlla universe nel config."
        )

    if u.get("extra_tickers"):
        pool += [t.upper() for t in u["extra_tickers"]]
    if u.get("exclude_tickers"):
        drop = {t.upper() for t in u["exclude_tickers"]}
        pool = [t for t in pool if t not in drop]
    pool = list(dict.fromkeys(pool))
    log(f"bacino     : {len(pool)} candidati da {source_used}")

    # ------------------------------------------------------- 2. ranking sul denaro
    quotes = provider.fetch_quotes(pool, log=log) if hasattr(provider, "fetch_quotes") \
        else provider.fetch(pool, cfg)
    kept, diag = rank_by_dollar_volume(
        quotes, top_n,
        min_price=float(u.get("min_price", 5)),
        min_market_cap=float(u.get("min_market_cap", 0) or 0),
    )
    diag["bacino"] = len(pool)
    diag["fonte_bacino"] = source_used
    tickers = [r["symbol"] for r in kept]

    log(f"universo   : primi {len(tickers)} per denaro scambiato "
        f"(soglia di taglio {_money(diag['taglio_dollar_volume'])})")
    if diag["senza_prezzo_o_volume"]:
        log(f"             {diag['senza_prezzo_o_volume']} candidati senza prezzo o volume, esclusi")

    cache.put("universe", key, {"tickers": tickers, "diag": diag})
    return tickers, diag


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _money(v) -> str:
    if v is None:
        return "n/d"
    v = float(v)
    if v >= 1e9:
        return f"{v/1e9:.2f} mld $"
    if v >= 1e6:
        return f"{v/1e6:.1f} mln $"
    return f"{v:.0f} $"
