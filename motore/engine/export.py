"""
Esportazione per il sito.

Produce UN SOLO file: site/data.json. Contiene i dati E il catalogo delle
metriche con i testi dei box, così il frontend resta stupido e non duplica
nessuna definizione: se cambi la spiegazione di una metrica in
engine/metrics.py, il box nel sito cambia al prossimo run.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metrics import BY_KEY, to_json_dict


def build_payload(result: dict, config: dict, extra: dict | None = None) -> dict:
    cols = list((config.get("output", {}) or {}).get("columns") or _default_columns(result))
    rows = []
    for r in result["rows"]:
        out: dict[str, Any] = {"rank": r.get("rank")}
        for c in cols:
            out[c] = r.get(c)
        out["score"] = r.get("score")
        out["coverage"] = r.get("coverage")
        out["reliable"] = r.get("reliable")
        out["_scores"] = {k: (None if v is None else round(v, 4))
                          for k, v in (r.get("_scores") or {}).items()}
        if r.get("_error"):
            out["_error"] = r["_error"]
        rows.append(out)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disclaimer": (
            "Punteggio relativo all'universo analizzato, a scopo informativo. "
            "Non è una raccomandazione di investimento."
        ),
        "meta": {**result["meta"], **(extra or {})},
        "columns": cols,
        "catalog": to_json_dict(),
        "rows": rows,
    }


def write_json(payload: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def write_js(payload: dict, path: str | Path) -> Path:
    """
    Stessa cosa di write_json ma come assegnazione JS.
    Serve perché aprendo il sito con doppio clic (file://) il browser blocca
    fetch() per CORS: index.html prova prima data.json e poi ricade su data.js,
    così la pagina funziona anche senza un server.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "window.__SCORE_DATA__ = " + json.dumps(payload, ensure_ascii=False) + ";",
        encoding="utf-8",
    )
    return p


def write_csv(payload: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cols = ["rank"] + payload["columns"] + ["score", "coverage", "reliable"]
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in payload["rows"]:
            w.writerow(r)
    return p


def _default_columns(result: dict) -> list[str]:
    base = ["symbol", "name", "sector", "price", "market_cap"]
    weighted = [k for k in result["meta"]["weights"] if k in BY_KEY]
    return list(dict.fromkeys(base + weighted))
