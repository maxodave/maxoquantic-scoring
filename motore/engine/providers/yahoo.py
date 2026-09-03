"""
Provider Yahoo Finance (API NON UFFICIALI).

Leggi prima questo
------------------
Yahoo non pubblica ne' documenta queste API e non offre alcuna garanzia:
i nomi dei campi cambiano, l'endpoint dello screener richiede cookie + "crumb",
e troppe richieste portano a un 429. Va benissimo per prototipare, non va in
produzione senza cache e senza fallback. Per questo il codice è scritto per
DEGRADARE, non per rompersi: ogni campo mancante diventa None e finisce nel
calcolo della copertura, così un punteggio costruito su pochi dati si vede.

Dipendenza: yfinance (gestisce cookie/crumb, rate limit e retry al posto nostro)
    pip install yfinance

Se un campo risulta vuoto per TUTTI i titoli, il nome del campo è cambiato:
lancia  python run.py doctor AAPL MSFT  e correggi `yahoo_info` nel catalogo
(engine/metrics.py). È l'unico punto da toccare.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..cache import TTL, Cache
from ..metrics import provider_fields

# Campi "di quota": cambiano ogni giorno. Sono gli unici che l'aggiornamento
# serale deve riscaricare. Tutto il resto viene dalla cache dei fondamentali.
QUOTE_KEYS = ("price", "volume", "avg_volume_3m", "market_cap", "change_pct", "name",
              "week52_low", "week52_high")


class YahooProvider:
    name = "yahoo"

    def __init__(self, pause: float = 0.25, cache: Optional[Cache] = None,
                 ttl_quote: float = TTL["quote"], ttl_fund: float = TTL["fundamentals"]):
        self.pause = pause  # cortesia verso l'endpoint: riduce i 429
        self.cache = cache if cache is not None else Cache()
        self.ttl_quote = ttl_quote
        self.ttl_fund = ttl_fund
        self._yf = None

    @property
    def yf(self):
        if self._yf is None:
            try:
                import yfinance as yf
            except ImportError as e:
                raise ImportError(
                    "Serve yfinance per il provider yahoo:  pip install yfinance\n"
                    "In alternativa usa provider: local con uno snapshot JSON/CSV."
                ) from e
            self._yf = yf
        return self._yf

    # ------------------------------------------------------------------ universo
    def universe(self, cfg: dict) -> list[str]:
        u = cfg.get("universe", {}) or {}
        mode = u.get("source", "tickers")

        if mode == "tickers":
            tickers = u.get("tickers") or []
            if not tickers:
                raise ValueError("universe.source=tickers ma universe.tickers è vuoto.")
            return list(dict.fromkeys(t.upper() for t in tickers))

        if mode == "file":
            from pathlib import Path
            syms = [ln.strip().upper() for ln in Path(u["path"]).read_text(encoding="utf-8").splitlines()]
            return [s for s in syms if s and not s.startswith("#")]

        if mode == "screener":
            return self._universe_from_screener(u)

        raise ValueError(f"universe.source sconosciuto: {mode!r}")

    def _universe_from_screener(self, u: dict) -> list[str]:
        """
        Ricostruisce lato nostro quello che fa la pagina "Most Actives":
        ordina per volume DESC e applica dei filtri. La differenza è che qui
        i filtri sono scritti nel config, quindi si sa sempre cosa c'è dentro.

        Usa yfinance.screen + EquityQuery (wrapper dell'endpoint non ufficiale
        /v1/finance/screener). Se l'API cambia, si alza un'eccezione parlante
        invece di restituire una lista silenziosamente sbagliata.
        """
        yf = self.yf
        if not hasattr(yf, "EquityQuery") or not hasattr(yf, "screen"):
            raise RuntimeError(
                "Questa versione di yfinance non espone EquityQuery/screen "
                "(serve >= 0.2.50).  pip install -U yfinance\n"
                "Alternativa: universe.source=file con una lista di ticker."
            )

        eq = yf.EquityQuery
        ops = [eq("eq", ["region", u.get("region", "us")])]

        # NOTA: gli id dei campi sono quelli dello screener Yahoo, non quelli
        # canonici del catalogo. Sono i due nomi che compaiono in metrics.py
        # come `yahoo_screener`.
        if (v := u.get("min_intraday_price")) is not None:
            ops.append(eq("gt", ["intradayprice", v]))
        if (v := u.get("min_market_cap")) is not None:
            ops.append(eq("gt", ["intradaymarketcap", v]))
        if (v := u.get("min_day_volume")) is not None:
            ops.append(eq("gt", ["dayvolume", v]))
        if exch := u.get("exchanges"):
            ops.append(eq("is-in", ["exchange"] + list(exch)))

        q = eq("and", ops)
        size = int(u.get("limit", 100))
        symbols: list[str] = []
        offset = 0
        page = min(size, 250)  # Yahoo tronca sopra 250 per richiesta

        while len(symbols) < size:
            res = yf.screen(
                q,
                offset=offset,
                size=min(page, size - len(symbols)),
                sortField=u.get("sort_field", "dayvolume"),
                sortAsc=bool(u.get("sort_asc", False)),
            )
            quotes = (res or {}).get("quotes") or []
            if not quotes:
                break
            symbols += [q_["symbol"] for q_ in quotes if q_.get("symbol")]
            offset += len(quotes)
            time.sleep(self.pause)

        if not symbols:
            raise RuntimeError(
                "Lo screener ha restituito zero titoli. Cause tipiche: filtri troppo "
                "stretti, id di campo cambiato, oppure rate limit (429). "
                "Prova con universe.source=tickers per isolare il problema."
            )
        return list(dict.fromkeys(symbols))[:size]

    # ------------------------------------------------------------------ rete
    def _retry(self, fn, what: str, log: Callable[[str], None]):
        """
        Tre tentativi con attesa crescente. Il 429 (troppe richieste) è la
        risposta più comune di queste API: attendere e riprovare è l'unica
        strategia che funziona, e comunque non oltre tre volte.
        """
        wait = 1.5
        for attempt in range(3):
            try:
                return fn()
            except Exception as e:
                msg = str(e)
                last = attempt == 2
                is_rate = "429" in msg or "Too Many Requests" in msg or "rate" in msg.lower()
                if last:
                    raise
                log(f"             {what}: {type(e).__name__}"
                    f"{' (limite di richieste)' if is_rate else ''}, riprovo fra {wait:.0f}s")
                time.sleep(wait)
                wait *= 3 if is_rate else 2
        return None

    # ------------------------------------------------------- quote (giornaliere)
    def fetch_quotes(self, tickers: list[str],
                     log: Callable[[str], None] = print,
                     completo: bool = True) -> list[dict[str, Any]]:
        """
        I dati che cambiano ogni giorno. Due modalita', per due usi diversi.

        `completo=False` — solo prezzo, volume e capitalizzazione, presi da
        `fast_info`: e' la via leggera, e serve a ordinare il bacino di 330
        candidati per denaro scambiato. Li' della variazione non importa a
        nessuno: si moltiplica prezzo per volume e si taglia.

        `completo=True` — anche la VARIAZIONE DI SEDUTA, che `fast_info` non
        sa dare. Ha `previousClose`, ma non e' la chiusura precedente vera:
        su NVIDIA dava 225,35 contro i 224,41 reali, cioe' +0,89% invece di
        +1,31%. Un errore piccolo in assoluto e inaccettabile qui, perche'
        finirebbe in una colonna che si chiama "Variazione %".

        Le due modalita' hanno CACHE SEPARATE: una riga leggera salvata dal
        bacino non deve poter essere riletta come se fosse completa. E' il
        difetto che ha fatto pubblicare per mezza giornata la variazione di
        ieri accanto al prezzo di oggi.
        """
        tipo = "quote" if completo else "quote_veloce"
        rows, from_cache, errors = [], 0, 0
        for i, sym in enumerate(tickers):
            hit = self.cache.get(tipo, sym, self.ttl_quote)
            if hit is not None:
                rows.append(hit)
                from_cache += 1
                continue
            try:
                row = self._retry(lambda s=sym: self._quote_one(s, completo),
                                  f"quota {sym}", log)
            except Exception as e:
                rows.append({"symbol": sym, "_error": f"{type(e).__name__}: {e}"})
                errors += 1
                continue
            self.cache.put(tipo, sym, row)
            rows.append(row)
            if self.pause and i < len(tickers) - 1:
                time.sleep(self.pause)

        scaricate = len(tickers) - from_cache - errors
        log(f"quote      : {scaricate} scaricate, {from_cache} dalla cache"
            + (f", {errors} in errore" if errors else "")
            + ("" if completo else "  (solo prezzo e volume: serve a ordinare il bacino)"))
        return rows

    def _quote_one(self, sym: str, completo: bool = True) -> dict[str, Any]:
        t = self.yf.Ticker(sym)
        row: dict[str, Any] = {"symbol": sym, "_source": "yahoo"}

        fi = None
        try:
            fi = t.fast_info
        except Exception:
            fi = None

        def g(obj, *names):
            for n in names:
                try:
                    v = obj[n] if isinstance(obj, dict) else getattr(obj, n, None)
                except Exception:
                    v = None
                if v is not None:
                    return v
            return None

        if fi is not None:
            row["price"] = _clean(g(fi, "last_price", "lastPrice"))
            row["volume"] = _clean(g(fi, "last_volume", "lastVolume"))
            row["avg_volume_3m"] = _clean(g(fi, "three_month_average_volume",
                                            "threeMonthAverageVolume"))
            row["market_cap"] = _clean(g(fi, "market_cap", "marketCap"))
            # fast_info li chiama year_high/year_low: sono gli stessi 52 settimane
            row["week52_high"] = _clean(g(fi, "year_high", "yearHigh"))
            row["week52_low"] = _clean(g(fi, "year_low", "yearLow"))

        # `info` e' piu' pesante ma e' l'unico posto dove la variazione di
        # seduta e' quella vera. Si chiede quando serve un dato completo, o
        # quando fast_info non ha coperto nemmeno prezzo e volume.
        if completo or row.get("price") is None or row.get("volume") is None:
            info = t.info or {}
            row["price"] = row.get("price") or _clean(info.get("regularMarketPrice"))
            row["volume"] = row.get("volume") or _clean(info.get("regularMarketVolume"))
            row["avg_volume_3m"] = row.get("avg_volume_3m") or _clean(info.get("averageVolume"))
            row["market_cap"] = row.get("market_cap") or _clean(info.get("marketCap"))
            row["name"] = _clean(info.get("longName") or info.get("shortName"))
            row["week52_high"] = row.get("week52_high") or _clean(info.get("fiftyTwoWeekHigh"))
            row["week52_low"] = row.get("week52_low") or _clean(info.get("fiftyTwoWeekLow"))
            cp = _clean(info.get("regularMarketChangePercent"))
            row["change_pct"] = None if cp is None else cp / 100.0
        return row

    # --------------------------------------------------------- seduta di mercato
    def market_session(self, riferimento: str = "SPY",
                       log: Callable[[str], None] = print) -> dict[str, Any] | None:
        """
        A QUALE SEDUTA si riferiscono i prezzi appena scaricati.

        Senza questo, l'unica data pubblicata è quella in cui il run è girato,
        che non è la stessa cosa: un aggiornamento lanciato la mattina italiana
        mostra la CHIUSURA DEL GIORNO PRIMA a New York. Dichiararlo è la
        differenza fra un dato datato e un dato che sembra di oggi.

        Costa UNA richiesta per run, non una per titolo: la borsa è la stessa
        per tutti i ticker americani, quindi si chiede a un solo strumento di
        riferimento (SPY) e si mette il risultato in cache come una quota.
        """
        hit = self.cache.get("session", riferimento, self.ttl_quote)
        if hit is not None:
            return hit
        try:
            info = self._retry(lambda: (self.yf.Ticker(riferimento).info or {}),
                               "seduta di mercato", log) or {}
        except Exception as e:
            log(f"seduta     : non determinata ({type(e).__name__})")
            return None

        epoch = info.get("regularMarketTime")
        tzname = info.get("exchangeTimezoneName") or "America/New_York"
        stato = str(info.get("marketState") or "").upper()
        if not epoch:
            return None

        try:
            from zoneinfo import ZoneInfo
            dt = datetime.fromtimestamp(float(epoch), ZoneInfo(tzname))
        except Exception:
            dt = datetime.fromtimestamp(float(epoch), timezone.utc)
            tzname = "UTC"

        # In seduta i prezzi sono intraday e si muovono ancora; fuori seduta
        # (PRE, POST, CLOSED, POSTPOST) l'ultimo scambio regolare È la chiusura.
        in_seduta = stato == "REGULAR"
        ses = {
            "data": dt.date().isoformat(),
            "ora": dt.strftime("%H:%M"),
            "fuso": tzname,
            "stato": stato or "?",
            "chiusa": not in_seduta,
            "riferimento": riferimento,
        }
        self.cache.put("session", riferimento, ses)
        return ses

    # ------------------------------------------------------ pre-mercato (minuti)
    def fetch_premarket(self, tickers: list[str],
                        log: Callable[[str], None] = print) -> list[dict[str, Any]]:
        """
        Prezzo e variazione delle contrattazioni prima dell'apertura.

        Costa una chiamata `info` per titolo: `fast_info` non li espone. Per
        questo la cache dura pochi minuti invece di sei ore — un dato di
        pre-mercato vecchio di un'ora non e' un dato di pre-mercato — e per
        questo e' un comando separato, non un pezzo dell'aggiornamento serale.

        Yahoo NON pubblica il volume pre-mercato: c'e' il prezzo, non c'e' con
        quanti scambi ci e' arrivato. Non si inventa: la colonna non esiste.
        """
        rows, from_cache, errors = [], 0, 0
        ttl = 300.0     # cinque minuti
        for i, sym in enumerate(tickers):
            hit = self.cache.get("premarket", sym, ttl)
            if hit is not None:
                rows.append(hit)
                from_cache += 1
                continue
            try:
                info = self._retry(lambda s=sym: (self.yf.Ticker(s).info or {}),
                                   f"pre-mercato {sym}", log) or {}
            except Exception as e:
                rows.append({"symbol": sym, "_error": f"{type(e).__name__}: {e}"})
                errors += 1
                continue
            row = {
                "symbol": sym,
                "premarket_price": _clean(info.get("preMarketPrice")),
                "premarket_change_pct": _clean(info.get("preMarketChangePercent")),
                "_premarket_time": info.get("preMarketTime"),
                "_market_state": info.get("marketState"),
            }
            row = normalize_percent_fields(row)
            self.cache.put("premarket", sym, row)
            rows.append(row)
            if self.pause and i < len(tickers) - 1:
                time.sleep(self.pause)

        scaricati = len(tickers) - from_cache - errors
        con_dato = sum(1 for r in rows if r.get("premarket_price") is not None)
        log(f"pre-mercato: {scaricati} scaricati, {from_cache} dalla cache"
            + (f", {errors} in errore" if errors else "")
            + f" | {con_dato}/{len(tickers)} con un prezzo pre-apertura")
        return rows

    # ------------------------------------------------ fondamentali (settimanali)
    def fetch_fundamentals(self, tickers: list[str],
                           log: Callable[[str], None] = print) -> list[dict[str, Any]]:
        fields = provider_fields()
        rows, from_cache, errors = [], 0, 0
        for i, sym in enumerate(tickers):
            hit = self.cache.get("fundamentals", sym, self.ttl_fund)
            if hit is not None:
                rows.append(hit)
                from_cache += 1
                continue
            try:
                info = self._retry(lambda s=sym: (self.yf.Ticker(s).info or {}),
                                   f"fondamentali {sym}", log)
            except Exception as e:
                rows.append({"symbol": sym, "_error": f"{type(e).__name__}: {e}"})
                errors += 1
                continue

            row: dict[str, Any] = {"symbol": sym, "_source": "yahoo"}
            for canonical, ykey in fields.items():
                row[canonical] = _clean(info.get(ykey))
            row = normalize_percent_fields(row)
            self.cache.put("fundamentals", sym, row)
            rows.append(row)
            if self.pause and i < len(tickers) - 1:
                time.sleep(self.pause)

        scaricati = len(tickers) - from_cache - errors
        log(f"fondament. : {scaricati} scaricati, {from_cache} dalla cache"
            + (f", {errors} in errore" if errors else ""))
        return rows

    # ------------------------------------------------------------------ unione
    def fetch(self, tickers: list[str], cfg: dict | None = None,
              log: Callable[[str], None] = print) -> list[dict[str, Any]]:
        """
        Fondamentali (cache lunga) sovrascritti dalle quote del giorno
        (cache corta). L'ordine conta: il prezzo di oggi deve vincere sempre.
        """
        fund = {r["symbol"]: r for r in self.fetch_fundamentals(tickers, log=log)}
        quot = {r["symbol"]: r for r in self.fetch_quotes(tickers, log=log)}
        out = []
        for sym in tickers:
            base = dict(fund.get(sym) or {"symbol": sym})
            q = quot.get(sym) or {}
            for k in QUOTE_KEYS:
                if q.get(k) is not None:
                    base[k] = q[k]
            if q.get("_error") and base.get("_error") is None and base.get("price") is None:
                base["_error"] = q["_error"]
            out.append(base)
        return out


# Yahoo espone le percentuali in DUE unita' diverse e non lo dichiara da
# nessuna parte. Verificato con `run.py doctor` e confrontando prezzo e
# chiusura precedente su piu' titoli:
#
#   FRAZIONE          profitMargins 0.2762 = 27,62%   52WeekChange 0.356 = +35,6%
#   PUNTI PERCENTUALI regularMarketChangePercent -1.106 = -1,106%
#
# Qui c'era un'euristica: "se il valore supera 1.5 e' in punti percentuali".
# Sbagliava in entrambe le direzioni. Un titolo sceso dell'1,1% nella seduta
# restava a -1.106 e il sito lo mostrava come -110,6%; e un titolo raddoppiato
# in dodici mesi (52WeekChange 1.6) sarebbe stato diviso per cento e mostrato
# a +1,6%. Le unita' adesso sono dichiarate campo per campo: se un giorno
# Yahoo cambia idea, `doctor` lo mostra e si corregge questa lista, non una
# soglia.
FRAZIONE = ("gross_margin", "net_margin", "roe", "roa",
            "revenue_growth", "earnings_growth", "week52_change")
PUNTI_PERCENTUALI = ("change_pct", "premarket_change_pct")


def normalize_percent_fields(row: dict) -> dict:
    """Porta tutte le percentuali a FRAZIONE, così il frontend ha una regola sola."""
    for k in PUNTI_PERCENTUALI:
        v = row.get(k)
        if v is not None:
            row[k] = v / 100.0
    return row


def _clean(v):
    if v is None or v == "" or v == "--":
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return None if (f != f or f in (float("inf"), float("-inf"))) else v
    return v
