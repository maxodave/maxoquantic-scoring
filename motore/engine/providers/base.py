"""
Interfaccia dei provider di dati.

Il motore non sa da dove arrivano i numeri. Questo serve a poter sostituire
Yahoo (non ufficiale, gratuito, senza garanzie) con un provider a pagamento
cambiando una riga di config, senza toccare scoring, metriche o frontend.

Contratto: universe() restituisce i ticker candidati, fetch() restituisce
righe con le CHIAVI CANONICHE del catalogo (engine/metrics.py), non i nomi
dei campi del provider. La traduzione è responsabilità del provider.
"""
from __future__ import annotations

from typing import Any, Protocol


class Provider(Protocol):
    name: str

    def universe(self, cfg: dict) -> list[str]:
        """Lista di ticker candidati."""
        ...

    def fetch(self, tickers: list[str], cfg: dict | None = None, log=print) -> list[dict[str, Any]]:
        """Una riga per ticker, con chiavi canoniche. Valori assenti = None."""
        ...

    def fetch_quotes(self, tickers: list[str], log=print) -> list[dict[str, Any]]:
        """Solo i campi che cambiano ogni giorno: prezzo, volume, capitalizzazione."""
        ...


def get_provider(name: str, cfg: dict | None = None):
    """Istanzia il provider e gli passa la configurazione della cache."""
    cfg = cfg or {}
    c = cfg.get("cache", {}) or {}
    if name in ("yahoo", "yfinance"):
        from ..cache import TTL, Cache
        from .yahoo import YahooProvider
        return YahooProvider(
            pause=float(c.get("pause", 0.25)),
            cache=Cache(c.get("dir", ".cache"), enabled=bool(c.get("enabled", True))),
            ttl_quote=float(c.get("ttl_quote", TTL["quote"])),
            ttl_fund=float(c.get("ttl_fundamentals", TTL["fundamentals"])),
        )
    if name in ("local", "file", "offline"):
        from .local import LocalProvider
        return LocalProvider(cfg)
    raise ValueError(f"provider sconosciuto: {name!r} (disponibili: yahoo, local)")
