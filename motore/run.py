#!/usr/bin/env python3
"""
CLI del motore di scoring.

    python run.py demo                      # gira sul fixture offline, zero rete
    python run.py run                        # gira con config/scoring.yml
    python run.py run -c config/mio.yml -o site/data.json
    python run.py doctor AAPL MSFT NVDA      # quali campi Yahoo rispondono davvero
    python run.py explain NVDA               # scomposizione del punteggio riga per riga
    python run.py fields                     # stampa il catalogo delle metriche

Il comando da lanciare per primo su una macchina nuova è `doctor`: dice quali
campi il provider restituisce oggi, prima di scoprirlo da una classifica sbagliata.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.cache import Cache                             # noqa: E402
from engine.config import load_config                      # noqa: E402
from engine.export import build_payload, write_csv, write_js, write_json  # noqa: E402
from engine.metrics import BY_KEY, CATALOG, SCOREABLE, provider_fields  # noqa: E402
from engine.providers.base import get_provider             # noqa: E402
from engine.scoring import add_derived, apply_filters, explain, score  # noqa: E402
from engine.universe import build as build_universe        # noqa: E402


# --------------------------------------------------------------------------- run
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    if getattr(args, "premarket", False):
        # Le due colonne del pre-mercato esistono SOLO in questo file: nel
        # dataset della chiusura sarebbero due colonne vuote da spiegare.
        cols = list((cfg.get("output", {}) or {}).get("columns") or [])
        for k in ("premarket_price", "premarket_change_pct"):
            if k not in cols:
                cols.insert(4, k) if k == "premarket_price" else cols.insert(5, k)
        cfg.setdefault("output", {})["columns"] = cols
    if getattr(args, "top", None):
        cfg.setdefault("universe", {})["top_n"] = int(args.top)
    if getattr(args, "no_cache", False):
        cfg.setdefault("cache", {})["enabled"] = False

    # Le quote restano valide 6 ore: un secondo `update` nello stesso
    # pomeriggio non tocca la rete. Quando invece si vuole davvero l'ultimo
    # prezzo - il mercato ha chiuso da poco, o si sospetta un dato sbagliato -
    # si buttano SOLO le quote: i fondamentali, che cambiano alla trimestrale,
    # restano dove sono e il run resta di quaranta secondi invece di sette minuti.
    if getattr(args, "refresh_quotes", False):
        c = cfg.get("cache", {}) or {}
        n = Cache(c.get("dir", ".cache"), enabled=True).clear("quote")
        print(f"cache      : {n} quote scartate, verranno riscaricate")

    prov = get_provider(cfg.get("provider", "yahoo"), cfg)
    top_n = int((cfg.get("universe") or {}).get("top_n", 150))
    print(f"provider   : {prov.name}  |  obiettivo: primi {top_n} per denaro scambiato")

    tickers, udiag = build_universe(cfg, prov, refresh=getattr(args, "refresh", False))
    if not tickers:
        print("\nUniverso vuoto. Controlla la sezione universe del config.")
        return 1

    rows = prov.fetch(tickers, cfg, log=lambda m: print(m))

    # Il pre-mercato NON sostituisce i prezzi di chiusura: si affianca. Le
    # valutazioni (P/E, EV/EBITDA...) restano quelle costruite sulla chiusura,
    # perche' mescolare un prezzo di pre-apertura con i fondamentali di ieri
    # produrrebbe multipli che non esistono da nessuna parte. Il pre-mercato
    # aggiunge due colonne dichiarate: dove sta il prezzo adesso e di quanto
    # si discosta dalla chiusura.
    if getattr(args, "premarket", False):
        if not hasattr(prov, "fetch_premarket"):
            print("Questo provider non espone il pre-mercato.")
            return 1
        pm = {r["symbol"]: r for r in prov.fetch_premarket(tickers, log=lambda m: print(m))}
        for r in rows:
            q = pm.get(r.get("symbol")) or {}
            for k in ("premarket_price", "premarket_change_pct"):
                if q.get(k) is not None:
                    r[k] = q[k]
            if q.get("_premarket_time"):
                r["_premarket_time"] = q["_premarket_time"]
    errs = [r for r in rows if r.get("_error")]
    if errs:
        print(f"attenzione : {len(errs)} titoli senza dati "
              f"({', '.join(str(r.get('symbol')) for r in errs[:5])}"
              f"{'...' if len(errs) > 5 else ''})")
    rows = [r for r in rows if not r.get("_error")]

    add_derived(rows)
    rows, dropped = apply_filters(rows, cfg.get("filters", {}) or {})
    if dropped:
        print("filtri     : " + ", ".join(f"{k} -{v}" for k, v in dropped.items()))
    print(f"analizzati : {len(rows)}")
    if not rows:
        print("\nNessuna riga sopravvive ai filtri. Allenta filters nel config.")
        return 1

    result = score(rows, cfg)
    m = result["meta"]
    print(f"scoring    : {m['method']} su {m['peer_group']} | "
          f"{m['n_reliable']}/{m['n']} righe affidabili (copertura >= {m['min_coverage']})")
    if m.get("empty_weights"):
        print("ATTENZIONE : pesi su metriche vuote per TUTTE le righe: "
              + ", ".join(m["empty_weights"]))
        print("             quel peso non entra nel punteggio. Verifica il nome del campo")
        print("             con `python run.py doctor`, oppure togli il peso dal config.")

    # A quale seduta si riferiscono questi prezzi. Una richiesta sola per run,
    # e il sito smette di dover far dedurre la data dall'ora del file.
    sessione = None
    if hasattr(prov, "market_session"):
        sessione = prov.market_session(log=lambda m: print(m))
        if sessione:
            print(f"seduta     : {'chiusura' if sessione['chiusa'] else 'in corso'} del "
                  f"{sessione['data']} ore {sessione['ora']} ({sessione['fuso']})")

    pm_meta = None
    if getattr(args, "premarket", False):
        con = sum(1 for r in result["rows"] if r.get("premarket_price") is not None)
        # L'ora del dato piu' recente: un pre-mercato di venti minuti fa e un
        # pre-mercato di tre ore fa non sono la stessa informazione.
        tempi = [r["_premarket_time"] for r in result["rows"] if r.get("_premarket_time")]
        quando = None
        if tempi:
            from datetime import datetime as _dt
            try:
                from zoneinfo import ZoneInfo
                d = _dt.fromtimestamp(max(tempi), ZoneInfo("America/New_York"))
                quando = {"data": d.date().isoformat(), "ora": d.strftime("%H:%M"),
                          "fuso": "America/New_York"}
            except Exception:
                quando = None
        pm_meta = {"righe_con_dato": con, "righe": len(result["rows"]),
                   "stato_mercato": (sessione or {}).get("stato"), "quando": quando}
        print(f"pre-mercato: {con}/{len(result['rows'])} titoli con un prezzo di pre-apertura")

    payload = build_payload(result, cfg, extra={
        "universe": udiag, "dropped": dropped,
        "provider": prov.name, "config": Path(args.config).name,
        "sessione": sessione, "premarket": pm_meta,
    })
    out = write_json(payload, args.out)
    print(f"scritto    : {out}")
    js = write_js(payload, Path(args.out).with_suffix(".js"))
    print(f"scritto    : {js}  (fallback per apertura con doppio clic)")
    if args.csv:
        print(f"scritto    : {write_csv(payload, args.csv)}")

    print("\ntop 10")
    print(f"{'#':>3} {'ticker':<8} {'score':>6} {'cov':>5}  azienda")
    for r in payload["rows"][:10]:
        flag = "" if r.get("reliable") else "  (dati insufficienti)"
        print(f"{r['rank']:>3} {str(r.get('symbol')):<8} {_f(r.get('score')):>6} "
              f"{_pct(r.get('coverage')):>5}  {str(r.get('name') or '')[:36]}{flag}")
    return 0


# ------------------------------------------------------------------- aggiorna
def cmd_update(args) -> int:
    """Il comando dell'uso quotidiano: un solo passo, nessun parametro."""
    rc = cmd_run(args)
    if rc == 0:
        print("\nAggiornamento completato. Il sito legge il nuovo data.json: "
              "non c'e' nient'altro da riavviare.")
    else:
        print("\nAggiornamento NON completato: i file precedenti sono rimasti intatti.")
    return rc


# ------------------------------------------------------------------ pre-mercato
def cmd_premarket(args) -> int:
    """
    La stessa tabella, con in piu' il prezzo di pre-apertura.

    Scrive un file separato (site/data-premarket.json): la pagina della
    chiusura non deve cambiare sotto i piedi quando si guarda il pre-mercato,
    e viceversa. Universo, fondamentali e quote vengono dalla cache: l'unica
    cosa che tocca la rete e' il pre-mercato stesso.
    """
    args.premarket = True
    args.out = args.out or str(ROOT / "site" / "data-premarket.json")
    args.csv = getattr(args, "csv", None)
    args.refresh = False
    args.no_cache = False
    args.refresh_quotes = False
    print("=== PRE-MERCATO (le contrattazioni prima dell'apertura di New York) ===\n")
    rc = cmd_run(args)
    if rc == 0:
        print("\nFatto. La scheda «Pre-mercato» della pagina legge questo file.")
    return rc


# -------------------------------------------------------------------- universo
def cmd_universe(args) -> int:
    """Ricalcola e mostra la classifica di liquidità, senza toccare il punteggio."""
    cfg = load_config(args.config)
    if args.top:
        cfg.setdefault("universe", {})["top_n"] = int(args.top)
    prov = get_provider(cfg.get("provider", "yahoo"), cfg)
    tickers, diag = build_universe(cfg, prov, refresh=not args.cached)

    print()
    for k, v in diag.items():
        print(f"  {k:<24} {v}")
    print(f"\n{len(tickers)} ticker:\n")
    for i in range(0, len(tickers), 10):
        print("  " + " ".join(t.ljust(6) for t in tickers[i:i + 10]))

    if args.save:
        Path(args.save).write_text(
            "# generato da `python run.py universe --save`\n" + "\n".join(tickers) + "\n",
            encoding="utf-8")
        print(f"\nsalvato: {args.save}")
    return 0


# ----------------------------------------------------------------------- cache
def cmd_cache(args) -> int:
    cfg = load_config(args.config)
    c = cfg.get("cache", {}) or {}
    cache = Cache(c.get("dir", ".cache"), enabled=True)
    if args.clear is not None:
        n = cache.clear(args.clear or None)
        print(f"cancellati {n} file di cache" + (f" ({args.clear})" if args.clear else ""))
        return 0
    st = cache.stats()
    if not st:
        print("cache vuota (o non ancora creata)")
        return 0
    print(f"cache in {cache.root}")
    for kind, n in st.items():
        print(f"  {kind:<14} {n:>5} file")
    print("\n  --clear            svuota tutto")
    print("  --clear quote      solo le quote (per forzare i prezzi di oggi)")
    return 0


# --------------------------------------------------------------------------- demo
def cmd_demo(args) -> int:
    args.config = str(ROOT / "config" / "demo.yml")
    # I dati finti NON toccano piu' site/data.json: la demo serve a verificare
    # che il motore giri, non a riempire il sito di societa' inventate. Chi
    # vuole guardarli apre site/_demo/data.json.
    args.out = args.out or str(ROOT / "site" / "_demo" / "data.json")
    args.top = getattr(args, "top", None)
    args.refresh = True
    args.no_cache = True
    print("=== DEMO OFFLINE (provider local, nessuna chiamata di rete) ===\n")
    return cmd_run(args)


# --------------------------------------------------------------------------- doctor
def cmd_doctor(args) -> int:
    """Verifica campo per campo cosa restituisce davvero il provider, oggi."""
    cfg = {"provider": args.provider, "cache": {"enabled": False}}
    prov = get_provider(args.provider, cfg)
    tickers = [t.upper() for t in args.tickers]
    print(f"provider {prov.name} | {len(tickers)} titoli di prova\n")

    try:
        rows = prov.fetch(tickers, cfg)
    except Exception as e:
        print(f"ERRORE nella fetch: {type(e).__name__}: {e}")
        return 1

    fields = provider_fields()
    print(f"{'metrica':<22} {'campo provider':<32} {'presenti':>9}   esempio")
    print("-" * 92)
    missing = []
    for canonical, ykey in fields.items():
        vals = [r.get(canonical) for r in rows if not r.get("_error")]
        have = [v for v in vals if v is not None]
        ratio = f"{len(have)}/{len(vals)}"
        sample = "" if not have else str(have[0])[:24]
        mark = " " if have else "!"
        print(f"{mark}{canonical:<21} {str(ykey):<32} {ratio:>9}   {sample}")
        if not have:
            missing.append((canonical, ykey))

    print()
    for canonical in ("dollar_volume", "rel_volume", "fcf_yield"):
        add_derived(rows)
        have = [r.get(canonical) for r in rows if r.get(canonical) is not None]
        print(f"  derivata {canonical:<16} calcolata su {len(have)}/{len(rows)}")

    if missing:
        print("\nCampi vuoti per TUTTI i titoli di prova -> nome probabilmente cambiato.")
        print("Correggi `yahoo_info` in engine/metrics.py per:")
        for c, y in missing:
            print(f"    {c:<22} (ora punta a {y!r})")
    else:
        print("\nTutti i campi mappati hanno risposto almeno una volta.")
    return 0


# --------------------------------------------------------------------------- explain
def cmd_explain(args) -> int:
    p = Path(args.data)
    if not p.exists():
        print(f"{p} non esiste: lancia prima `python run.py run` o `python run.py demo`.")
        return 1
    payload = json.loads(p.read_text(encoding="utf-8"))
    sym = args.ticker.upper()
    row = next((r for r in payload["rows"] if str(r.get("symbol", "")).upper() == sym), None)
    if not row:
        print(f"{sym} non è nel dataset ({len(payload['rows'])} righe).")
        return 1

    weights = payload["meta"]["weights"]
    row = {**row, "_scores": row.get("_scores", {})}
    print(f"{sym} — {row.get('name') or ''}")
    print(f"punteggio {row.get('score')}/100 | copertura {_pct(row.get('coverage'))} | rank {row.get('rank')}\n")
    print(f"{'metrica':<22} {'valore':>14} {'perc.':>7} {'peso':>6} {'punti':>7}")
    print("-" * 62)
    for e in explain(row, weights):
        if e["missing"]:
            print(f"{e['label']:<22} {'--':>14} {'--':>7} {e['weight']:>6} {'0.00':>7}  dato mancante")
        else:
            print(f"{e['label']:<22} {_f(e['raw'], 4):>14} {e['score01']*100:>6.0f}% "
                  f"{e['weight']:>6} {e['contribution_pts']:>7}")
    return 0


# --------------------------------------------------------------------------- fields
def cmd_fields(args) -> int:
    print(f"{len(CATALOG)} metriche | {len(SCOREABLE)} utilizzabili nel punteggio\n")
    group = None
    for m in CATALOG:
        if m.group != group:
            group = m.group
            print(f"\n[{group}]")
        d = {"higher_better": "^", "lower_better": "v", "target_band": "~", "context": "."}[m.direction]
        print(f"  {d} {m.key:<20} {m.label:<24} {m.unit:<8} {m.yahoo_info or '(derivata)'}")
    print("\n  ^ alto=meglio   v basso=meglio   ~ fascia ottimale   . solo contesto")
    return 0


# --------------------------------------------------------------------------- util
def _f(v, nd=2):
    if v is None:
        return "--"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(f) >= 1e9:
        return f"{f/1e9:.2f}B"
    if abs(f) >= 1e6:
        return f"{f/1e6:.2f}M"
    return f"{f:.{nd}f}"


def _pct(v):
    return "--" if v is None else f"{float(v)*100:.0f}%"


def _accepts_cfg(fn) -> bool:
    import inspect
    try:
        return len(inspect.signature(fn).parameters) >= 2
    except (TypeError, ValueError):
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run.py", description="Motore di scoring aziendale")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for nome, aiuto, fn in (
        ("run", "scarica, filtra, assegna il punteggio, esporta", cmd_run),
        ("update", "aggiornamento quotidiano: fa tutto in un passo", cmd_update),
    ):
        r = sub.add_parser(nome, help=aiuto)
        r.add_argument("-c", "--config", default=str(ROOT / "config" / "scoring.yml"))
        r.add_argument("-o", "--out", default=str(ROOT / "site" / "data.json"))
        r.add_argument("--csv", default=None, help="esporta anche in CSV")
        r.add_argument("--top", type=int, default=None,
                       help="quanti titoli tenere (default: universe.top_n del config)")
        r.add_argument("--refresh", action="store_true",
                       help="ricalcola l'universo invece di usare quello in cache")
        r.add_argument("--no-cache", action="store_true", help="ignora la cache, riscarica tutto")
        r.set_defaults(premarket=False)
        r.add_argument("--refresh-quotes", action="store_true",
                       help="riscarica i prezzi anche se in cache (i fondamentali restano)")
        r.set_defaults(func=fn)

    pm = sub.add_parser("premarket", help="la stessa tabella con il prezzo di pre-apertura")
    pm.add_argument("-c", "--config", default=str(ROOT / "config" / "scoring.yml"))
    pm.add_argument("-o", "--out", default=None)
    pm.add_argument("--top", type=int, default=None)
    pm.set_defaults(func=cmd_premarket)

    un = sub.add_parser("universe", help="mostra i primi N per denaro scambiato")
    un.add_argument("-c", "--config", default=str(ROOT / "config" / "scoring.yml"))
    un.add_argument("--top", type=int, default=None)
    un.add_argument("--cached", action="store_true", help="usa la cache invece di ricalcolare")
    un.add_argument("--save", default=None, help="salva la lista in un file di testo")
    un.set_defaults(func=cmd_universe)

    ca = sub.add_parser("cache", help="stato della cache, oppure svuotala")
    ca.add_argument("-c", "--config", default=str(ROOT / "config" / "scoring.yml"))
    ca.add_argument("--clear", nargs="?", const="", default=None,
                    help="svuota la cache (opzionale: quote | fundamentals | universe)")
    ca.set_defaults(func=cmd_cache)

    d = sub.add_parser("demo", help="gira offline sul fixture di esempio")
    d.add_argument("-o", "--out", default=None)
    d.add_argument("--csv", default=None)
    d.add_argument("--top", type=int, default=None)
    d.set_defaults(func=cmd_demo)

    doc = sub.add_parser("doctor", help="verifica quali campi il provider restituisce davvero")
    doc.add_argument("tickers", nargs="+")
    doc.add_argument("--provider", default="yahoo")
    doc.set_defaults(func=cmd_doctor)

    e = sub.add_parser("explain", help="scomposizione del punteggio di un titolo")
    e.add_argument("ticker")
    e.add_argument("--data", default=str(ROOT / "site" / "data.json"))
    e.set_defaults(func=cmd_explain)

    f = sub.add_parser("fields", help="stampa il catalogo delle metriche")
    f.set_defaults(func=cmd_fields)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
