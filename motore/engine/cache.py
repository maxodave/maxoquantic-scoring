"""
Cache su disco, con scadenze diverse per tipo di dato.

Il punto non è la velocità, è non farsi bloccare. 150 titoli al giorno contro
API non documentate significa migliaia di richieste al mese: senza cache si
finisce nei `429 Too Many Requests` e l'aggiornamento serale salta in silenzio.

La divisione che rende sostenibile il tutto:

    quote        prezzo, volume, volume medio, capitalizzazione   -> scade in ORE
    fundamentals margini, multipli, debito, cassa, crescita       -> scade in GIORNI

Perché funziona: i fondamentali cambiano quattro volte l'anno, alla
trimestrale. Riscaricarli ogni sera è lavoro buttato. I prezzi invece cambiano
ogni giorno, ed è l'unica parte che l'aggiornamento quotidiano deve rifare.
Risultato: il run serale tocca la rete per un solo blocco di dati.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class Cache:
    def __init__(self, root: str | Path = ".cache", enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled

    # ------------------------------------------------------------------
    def _path(self, kind: str, key: str) -> Path:
        # Nessun punto e nessun separatore nel nome: il ticker arriva da una
        # risposta di rete, e un nome di file non deve poter uscire dalla cartella.
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in key.upper())
        kind = "".join(c for c in kind if c.isalnum() or c in "-_") or "misc"
        return self.root / kind / ((safe or "vuoto") + ".json")

    def get(self, kind: str, key: str, ttl_seconds: float) -> Optional[dict]:
        """Restituisce il contenuto se esiste ed è più giovane del TTL, altrimenti None."""
        if not self.enabled or ttl_seconds <= 0:
            return None
        p = self._path(kind, key)
        if not p.exists():
            return None
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None                      # cache corrotta = cache assente
        if time.time() - float(blob.get("_ts", 0)) > ttl_seconds:
            return None
        return blob.get("data")

    def put(self, kind: str, key: str, data: Any) -> None:
        if not self.enabled:
            return
        p = self._path(kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"_ts": time.time(), "data": data}, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(p)                   # scrittura atomica: mai un file mezzo scritto
        except OSError:
            pass                             # la cache è un'ottimizzazione, non deve mai fermare il run

    def age(self, kind: str, key: str) -> Optional[float]:
        """Età in secondi del dato in cache, None se non c'è."""
        p = self._path(kind, key)
        if not p.exists():
            return None
        try:
            return time.time() - float(json.loads(p.read_text(encoding="utf-8")).get("_ts", 0))
        except (json.JSONDecodeError, OSError):
            return None

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        if not self.root.exists():
            return out
        for d in sorted(self.root.iterdir()):
            if d.is_dir():
                out[d.name] = len(list(d.glob("*.json")))
        return out

    def clear(self, kind: str | None = None) -> int:
        target = self.root / kind if kind else self.root
        n = 0
        if target.exists():
            for f in target.rglob("*.json"):
                try:
                    f.unlink()
                    n += 1
                except OSError:
                    pass
        return n


# TTL di default, sovrascrivibili da config (sezione `cache`)
TTL = {
    "quote": 6 * 3600,          # 6 ore: una seduta
    "fundamentals": 7 * 86400,  # 7 giorni: cambiano alla trimestrale
    "universe": 7 * 86400,      # 7 giorni: la classifica di liquidità è stabile
}
