"""
Provider offline: legge righe già pronte da JSON o CSV.

Serve a tre cose:
  * far girare e testare il motore senza rete (i test in tests/ usano questo)
  * congelare uno snapshot e rendere il punteggio riproducibile
  * far girare il sito quando l'API di Yahoo cambia o smette di rispondere
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class LocalProvider:
    name = "local"

    def __init__(self, cfg: dict | None = None):
        self._cfg = cfg or {}

    def universe(self, cfg: dict) -> list[str]:
        self._cfg = cfg or self._cfg
        rows = self._load(cfg)
        return [r["symbol"] for r in rows if r.get("symbol")]

    def fetch(self, tickers: list[str], cfg: dict | None = None,
              log=print) -> list[dict[str, Any]]:
        rows = self._load(cfg or {})
        want = set(tickers)
        return [r for r in rows if r.get("symbol") in want] if want else rows

    # Stessa interfaccia del provider Yahoo, così l'universo e i test girano
    # identici offline: qui quote e fondamentali stanno nello stesso file.
    def fetch_quotes(self, tickers: list[str], log=print) -> list[dict[str, Any]]:
        return self.fetch(tickers, self._cfg)

    def fetch_fundamentals(self, tickers: list[str], log=print) -> list[dict[str, Any]]:
        return self.fetch(tickers, self._cfg)

    # ------------------------------------------------------------------
    def _load(self, cfg: dict) -> list[dict[str, Any]]:
        path = Path((cfg.get("universe") or {}).get("path") or cfg.get("path") or "")
        if not path.exists():
            raise FileNotFoundError(
                f"provider 'local': file non trovato: {path}. "
                "Imposta universe.path nel config."
            )
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = data["rows"] if isinstance(data, dict) and "rows" in data else data
        else:
            with path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        return [self._coerce(r) for r in rows]

    @staticmethod
    def _coerce(r: dict) -> dict:
        """CSV consegna tutto come stringa: riporta i numeri a numeri, '' -> None."""
        out = {}
        for k, v in r.items():
            if v is None or (isinstance(v, str) and v.strip() in ("", "--", "N/A", "null")):
                out[k] = None
                continue
            if isinstance(v, (int, float)):
                out[k] = v
                continue
            s = str(v).strip().replace(",", "")
            try:
                out[k] = float(s) if ("." in s or "e" in s.lower()) else int(s)
            except ValueError:
                out[k] = v
        return out
