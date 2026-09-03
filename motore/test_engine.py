"""
Test del motore. Tutto offline: nessuna chiamata di rete.
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.config import load_config
from engine.export import build_payload
from engine.metrics import BY_KEY, CATALOG, DERIVED, SCOREABLE
from engine.normalize import band_scores, percentile_scores, quantile, zscore_scores
from engine.cache import Cache
from engine.providers.local import LocalProvider
from engine.providers.yahoo import QUOTE_KEYS, YahooProvider, normalize_percent_fields
from engine.universe import build as build_universe
from engine.universe import rank_by_dollar_volume, read_seed
from engine.scoring import add_derived, apply_filters, explain, score

FIXTURE = ROOT / "tests" / "fixtures" / "universe_demo.json"
DEMO_CFG = ROOT / "config" / "demo.yml"


class TestNormalize(unittest.TestCase):
    def test_percentile_monotona_e_agli_estremi(self):
        s = percentile_scores([1, 2, 3, 4, 5], winsor=(0.0, 1.0))
        self.assertEqual(s[0], 0.0)
        self.assertEqual(s[-1], 1.0)
        self.assertEqual(s, sorted(s))

    def test_pari_merito_stesso_punteggio(self):
        s = percentile_scores([10, 10, 10, 20], winsor=(0.0, 1.0))
        self.assertEqual(s[0], s[1])
        self.assertEqual(s[1], s[2])
        self.assertLess(s[0], s[3])

    def test_none_resta_none_e_non_diventa_zero(self):
        s = percentile_scores([1, None, 3], winsor=(0.0, 1.0))
        self.assertIsNone(s[1])
        self.assertNotIn(0.0, [s[1]])

    def test_nan_e_inf_trattati_come_mancanti(self):
        s = percentile_scores([1.0, float("nan"), float("inf"), 4.0], winsor=(0.0, 1.0))
        self.assertIsNone(s[1])
        self.assertIsNone(s[2])

    def test_winsorize_limita_outlier(self):
        """Un outlier estremo non deve schiacciare tutti gli altri sullo stesso punteggio."""
        vals = [10, 11, 12, 13, 100000]
        s = percentile_scores(vals, winsor=(0.05, 0.95))
        self.assertGreater(s[1] - s[0], 0.0)          # i piccoli restano distinguibili
        self.assertEqual(max(s), s[-1])

    def test_serie_costante_non_esplode(self):
        s = percentile_scores([5, 5, 5])
        # tutti pari merito -> tutti neutri (0.5), non tutti a zero:
        # un punteggio di 0 sarebbe un giudizio, qui non c'è nulla da giudicare
        self.assertTrue(all(x == 0.5 for x in s))
        z = zscore_scores([5, 5, 5])
        self.assertTrue(all(abs(x - 0.5) < 1e-9 for x in z))

    def test_un_solo_valore_diventa_neutro(self):
        self.assertEqual(percentile_scores([42]), [0.5])

    def test_band_premia_la_fascia_non_il_massimo(self):
        s = band_scores([0.5, 1.5, 2.5, 8.0], (1.2, 3.0))
        self.assertEqual(s[1], 1.0)
        self.assertEqual(s[2], 1.0)
        self.assertLess(s[0], 1.0)
        self.assertEqual(s[3], 0.0)   # 8.0 è oltre una larghezza di fascia
        self.assertLess(s[3], s[1])

    def test_quantile_interpola(self):
        self.assertEqual(quantile([0, 10], 0.5), 5.0)


class TestDerivate(unittest.TestCase):
    def test_dollar_volume_e_rel_volume(self):
        rows = [{"price": 2.0, "volume": 100, "avg_volume_3m": 50}]
        add_derived(rows)
        self.assertEqual(rows[0]["dollar_volume"], 200.0)
        self.assertEqual(rows[0]["rel_volume"], 2.0)

    def test_niente_divisione_per_zero(self):
        rows = [{"price": 1, "volume": 10, "avg_volume_3m": 0, "fcf": 5, "market_cap": 0}]
        add_derived(rows)
        self.assertIsNone(rows[0]["rel_volume"])
        self.assertIsNone(rows[0]["fcf_yield"])

    def test_idempotente(self):
        rows = [{"price": 2.0, "volume": 100, "dollar_volume": 999}]
        add_derived(rows)
        self.assertEqual(rows[0]["dollar_volume"], 999)   # non sovrascrive

    def test_il_penny_stock_perde_contro_la_large_cap_sul_dollar_volume(self):
        """Il cuore del problema 'Most Actives': il volume in pezzi mente."""
        rows = [
            {"symbol": "PENNY", "price": 1.24, "volume": 488_328_000},
            {"symbol": "LARGE", "price": 222.33, "volume": 87_096_000},
        ]
        add_derived(rows)
        self.assertGreater(rows[0]["volume"], rows[1]["volume"])            # per volume vince PENNY
        self.assertLess(rows[0]["dollar_volume"], rows[1]["dollar_volume"])  # per denaro vince LARGE


class TestFiltri(unittest.TestCase):
    def test_conta_gli_scarti_per_motivo(self):
        rows = [
            {"symbol": "A", "price": 1.0, "market_cap": 1e9, "dollar_volume": 1e7},
            {"symbol": "B", "price": 50.0, "market_cap": 1e6, "dollar_volume": 1e7},
            {"symbol": "C", "price": 50.0, "market_cap": 1e9, "dollar_volume": 1e7},
        ]
        kept, dropped = apply_filters(rows, {"min_price": 5, "min_market_cap": 1e8})
        self.assertEqual([r["symbol"] for r in kept], ["C"])
        self.assertEqual(sum(dropped.values()), 2)
        self.assertIn("min_price<5", dropped)

    def test_dato_mancante_non_passa_un_filtro_minimo(self):
        kept, _ = apply_filters([{"symbol": "X", "price": None}], {"min_price": 5})
        self.assertEqual(kept, [])


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "normalization": {"method": "percentile", "peer_group": "all"},
            "scoring": {"min_coverage": 0.5, "weights": {"roe": 1.0, "pe_trailing": 1.0}},
        }

    def test_direzione_lower_better_invertita(self):
        rows = [
            {"symbol": "CARO", "roe": 0.2, "pe_trailing": 90},
            {"symbol": "ECONOMICO", "roe": 0.2, "pe_trailing": 8},
        ]
        res = score(rows, self.cfg)
        by = {r["symbol"]: r for r in res["rows"]}
        self.assertGreater(by["ECONOMICO"]["score"], by["CARO"]["score"])

    def test_dato_mancante_riduce_la_copertura_non_azzera_il_punteggio(self):
        rows = [
            {"symbol": "PIENA", "roe": 0.30, "pe_trailing": 10},
            {"symbol": "META", "roe": 0.30, "pe_trailing": None},
            {"symbol": "TERZA", "roe": 0.05, "pe_trailing": 40},
        ]
        res = score(rows, self.cfg)
        by = {r["symbol"]: r for r in res["rows"]}
        self.assertAlmostEqual(by["META"]["coverage"], 0.5)
        self.assertAlmostEqual(by["PIENA"]["coverage"], 1.0)
        # META ha il ROE migliore: senza P/E il suo punteggio resta alto,
        # perché il peso mancante viene redistribuito e non messo a zero.
        self.assertGreater(by["META"]["score"], by["TERZA"]["score"])

    def test_sotto_min_coverage_la_riga_e_marcata(self):
        cfg = {**self.cfg, "scoring": {"min_coverage": 0.9, "weights": {"roe": 1.0, "pe_trailing": 1.0}}}
        rows = [{"symbol": "A", "roe": 0.1, "pe_trailing": 10},
                {"symbol": "B", "roe": 0.2, "pe_trailing": None}]
        res = score(rows, cfg)
        by = {r["symbol"]: r for r in res["rows"]}
        self.assertTrue(by["A"]["reliable"])
        self.assertFalse(by["B"]["reliable"])
        # le righe inaffidabili finiscono in fondo alla classifica
        self.assertLess(by["A"]["rank"], by["B"]["rank"])

    def test_riga_completamente_vuota_non_rompe(self):
        rows = [{"symbol": "A", "roe": 0.1, "pe_trailing": 10}, {"symbol": "VUOTA"}]
        res = score(rows, self.cfg)
        vuota = next(r for r in res["rows"] if r["symbol"] == "VUOTA")
        self.assertIsNone(vuota["score"])
        self.assertEqual(vuota["coverage"], 0.0)
        self.assertFalse(vuota["reliable"])

    def test_pesi_assenti_errore_esplicito(self):
        with self.assertRaises(ValueError):
            score([{"symbol": "A"}], {"scoring": {"weights": {}}})

    def test_metrica_fuori_catalogo_errore_esplicito(self):
        with self.assertRaises(ValueError) as ctx:
            score([{"symbol": "A"}], {"scoring": {"weights": {"non_esiste": 1}}})
        self.assertIn("non_esiste", str(ctx.exception))

    def test_confronto_per_settore_isola_i_settori(self):
        """Un P/E alto nel settore caro non deve essere punito come nel settore economico."""
        rows = [
            {"symbol": "T1", "sector": "Tech", "roe": 0.3, "pe_trailing": 40},
            {"symbol": "T2", "sector": "Tech", "roe": 0.3, "pe_trailing": 60},
            {"symbol": "U1", "sector": "Utility", "roe": 0.3, "pe_trailing": 12},
            {"symbol": "U2", "sector": "Utility", "roe": 0.3, "pe_trailing": 18},
        ]
        cfg = {
            "normalization": {"method": "percentile", "peer_group": "sector", "min_peers": 2},
            "scoring": {"min_coverage": 0.5, "weights": {"roe": 1.0, "pe_trailing": 1.0}},
        }
        by = {r["symbol"]: r for r in score(rows, cfg)["rows"]}
        # T1 (il più economico del suo settore) prende lo stesso punteggio di U1
        self.assertAlmostEqual(by["T1"]["score"], by["U1"]["score"])
        self.assertGreater(by["T1"]["score"], by["T2"]["score"])

    def test_settore_troppo_piccolo_ricade_sull_universo(self):
        rows = [{"symbol": f"A{i}", "sector": "Big", "roe": i / 10, "pe_trailing": 10 + i} for i in range(10)]
        rows.append({"symbol": "SOLO", "sector": "Nicchia", "roe": 0.5, "pe_trailing": 15})
        cfg = {
            "normalization": {"method": "percentile", "peer_group": "sector", "min_peers": 8},
            "scoring": {"min_coverage": 0.5, "weights": {"roe": 1.0}},
        }
        res = score(rows, cfg)
        self.assertIn("__universe_fallback__", res["meta"]["peer_groups"])
        solo = next(r for r in res["rows"] if r["symbol"] == "SOLO")
        self.assertIsNotNone(solo["score"])   # non è 0.5 di default: è stato confrontato

    def test_zscore_come_metodo_alternativo(self):
        cfg = {
            "normalization": {"method": "zscore", "peer_group": "all"},
            "scoring": {"min_coverage": 0.5, "weights": {"roe": 1.0}},
        }
        rows = [{"symbol": s, "roe": v} for s, v in [("A", 0.05), ("B", 0.15), ("C", 0.35)]]
        by = {r["symbol"]: r for r in score(rows, cfg)["rows"]}
        self.assertGreater(by["C"]["score"], by["B"]["score"])
        self.assertGreater(by["B"]["score"], by["A"]["score"])

    def test_deterministico(self):
        rows = lambda: [{"symbol": f"S{i}", "roe": (i * 7 % 11) / 10, "pe_trailing": 5 + (i * 3 % 17)}
                        for i in range(30)]
        a = [(r["symbol"], r["score"]) for r in score(rows(), self.cfg)["rows"]]
        b = [(r["symbol"], r["score"]) for r in score(rows(), self.cfg)["rows"]]
        self.assertEqual(a, b)

    def test_avvisa_sui_pesi_vuoti_per_tutte_le_righe(self):
        """Un peso su una colonna interamente vuota non entra nel punteggio: va detto."""
        cfg = {
            "normalization": {"peer_group": "all"},
            "scoring": {"weights": {"roe": 1.0, "roic": 1.0}},
        }
        meta = score([{"symbol": "A", "roe": 0.1}, {"symbol": "B", "roe": 0.2}], cfg)["meta"]
        self.assertIn("roic", meta["empty_weights"])
        self.assertNotIn("roe", meta["empty_weights"])

    def test_una_derivata_calcolabile_non_e_segnalata_come_vuota(self):
        cfg = {"normalization": {"peer_group": "all"},
               "scoring": {"weights": {"fcf_yield": 1.0}}}
        rows = [{"symbol": "A", "fcf": 1e9, "market_cap": 1e10},
                {"symbol": "B", "fcf": 2e8, "market_cap": 1e10}]
        meta = score(rows, cfg)["meta"]
        self.assertEqual(meta["empty_weights"], [])

    def test_explain_somma_al_punteggio(self):
        rows = [{"symbol": "A", "roe": 0.3, "pe_trailing": 10},
                {"symbol": "B", "roe": 0.1, "pe_trailing": 30}]
        res = score(rows, self.cfg)
        r = res["rows"][0]
        tot = sum(e["contribution_pts"] or 0 for e in explain(r, res["meta"]["weights"]))
        self.assertAlmostEqual(tot, r["score"], places=1)


class TestCatalogo(unittest.TestCase):
    def test_chiavi_uniche(self):
        keys = [m.key for m in CATALOG]
        self.assertEqual(len(keys), len(set(keys)))

    def test_ogni_metrica_ha_un_box_completo(self):
        for m in CATALOG:
            for campo in ("cos_e", "come_si_legge", "trappola"):
                testo = getattr(m.box, campo)
                self.assertTrue(testo and len(testo) > 20, f"{m.key}.{campo} troppo corto")

    def test_target_band_ha_la_fascia(self):
        for m in CATALOG:
            if m.direction == "target_band":
                self.assertIsNotNone(m.band, f"{m.key} è target_band ma non ha band")
                self.assertLess(m.band[0], m.band[1])

    def test_le_derivate_non_hanno_campo_provider(self):
        for k in DERIVED:
            self.assertIsNone(BY_KEY[k].yahoo_info, f"{k} è derivata: non deve avere yahoo_info")

    def test_scoreable_esclude_il_contesto(self):
        for k in SCOREABLE:
            self.assertNotEqual(BY_KEY[k].direction, "context")

    def test_i_pesi_del_config_esistono_nel_catalogo(self):
        for cfg_path in (ROOT / "config" / "scoring.yml", DEMO_CFG):
            cfg = load_config(cfg_path)
            for k in cfg["scoring"]["weights"]:
                self.assertIn(k, BY_KEY, f"{cfg_path.name}: peso su metrica inesistente {k!r}")

    def test_le_colonne_output_esistono_nel_catalogo(self):
        for cfg_path in (ROOT / "config" / "scoring.yml", DEMO_CFG):
            cfg = load_config(cfg_path)
            for c in cfg["output"]["columns"]:
                self.assertIn(c, BY_KEY, f"{cfg_path.name}: colonna inesistente {c!r}")


class TestCache(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.c = Cache(self.dir)

    def test_scrive_e_rilegge(self):
        self.c.put("quote", "AAPL", {"price": 1.5})
        self.assertEqual(self.c.get("quote", "AAPL", 3600), {"price": 1.5})

    def test_il_ttl_fa_scadere(self):
        self.c.put("quote", "AAPL", {"price": 1.5})
        self.assertIsNone(self.c.get("quote", "AAPL", -1))

    def test_ttl_zero_significa_ignora_la_cache(self):
        self.c.put("quote", "AAPL", {"price": 1.5})
        self.assertIsNone(self.c.get("quote", "AAPL", 0))

    def test_assente_restituisce_none(self):
        self.assertIsNone(self.c.get("quote", "MAI_VISTO", 3600))

    def test_cache_corrotta_vale_come_assente(self):
        self.c.put("quote", "AAPL", {"price": 1})
        p = Path(self.dir) / "quote" / "AAPL.json"
        p.write_text("{ questo non e' json", encoding="utf-8")
        self.assertIsNone(self.c.get("quote", "AAPL", 3600))   # non solleva

    def test_ticker_con_caratteri_strani_non_esce_dalla_cartella(self):
        self.c.put("quote", "../../etc/passwd", {"x": 1})
        files = [f.name for f in (Path(self.dir) / "quote").glob("*.json")]
        self.assertTrue(all(".." not in f for f in files))
        self.assertEqual(self.c.get("quote", "../../etc/passwd", 3600), {"x": 1})

    def test_disabilitata_non_scrive_nulla(self):
        import tempfile
        d = tempfile.mkdtemp()
        c = Cache(d, enabled=False)
        c.put("quote", "AAPL", {"price": 1})
        self.assertIsNone(c.get("quote", "AAPL", 3600))
        self.assertEqual(c.stats(), {})

    def test_stats_e_clear(self):
        self.c.put("quote", "A", {}); self.c.put("fundamentals", "A", {})
        self.assertEqual(self.c.stats(), {"fundamentals": 1, "quote": 1})
        self.assertEqual(self.c.clear("quote"), 1)
        self.assertEqual(self.c.stats().get("quote", 0), 0)


class TestUniverso(unittest.TestCase):
    def test_read_seed_ignora_commenti_e_duplicati(self):
        p = ROOT / "tests" / "fixtures" / "_seed.txt"
        p.write_text("# commento\nAAPL\n\nmsft  # inline\nAAPL\n", encoding="utf-8")
        try:
            self.assertEqual(read_seed(p), ["AAPL", "MSFT"])
        finally:
            p.unlink(missing_ok=True)

    def test_la_lista_seed_del_pacchetto_e_leggibile(self):
        syms = read_seed(ROOT / "config" / "seed_universe.txt")
        self.assertGreater(len(syms), 250)         # bacino ampio per pescare 150
        self.assertEqual(len(syms), len(set(syms)))
        self.assertIn("NVDA", syms)
        self.assertTrue(all(s == s.upper() and " " not in s for s in syms))

    def test_ordina_per_denaro_non_per_pezzi(self):
        """Il caso GoPro/NVIDIA: e' il motivo per cui esiste questo modulo."""
        rows = [
            {"symbol": "GPRO", "price": 1.24, "volume": 488_328_000},
            {"symbol": "NVDA", "price": 222.33, "volume": 87_096_000},
        ]
        kept, _ = rank_by_dollar_volume(rows, 2)
        self.assertEqual([r["symbol"] for r in kept], ["NVDA", "GPRO"])

    def test_soglia_di_prezzo_elimina_i_penny_stock(self):
        rows = [
            {"symbol": "PENNY", "price": 0.02, "volume": 900_000_000},
            {"symbol": "BUONO", "price": 50.0, "volume": 1_000_000},
        ]
        kept, diag = rank_by_dollar_volume(rows, 10, min_price=5)
        self.assertEqual([r["symbol"] for r in kept], ["BUONO"])
        self.assertEqual(diag["sotto_le_soglie"], 1)

    def test_i_buchi_di_dati_sono_contati_a_parte(self):
        """Senza prezzo o volume non e' un titolo illiquido: e' un dato mancante."""
        rows = [{"symbol": "A", "price": None, "volume": 10},
                {"symbol": "B", "price": 10, "volume": None},
                {"symbol": "C", "price": 10, "volume": 10}]
        kept, diag = rank_by_dollar_volume(rows, 10)
        self.assertEqual([r["symbol"] for r in kept], ["C"])
        self.assertEqual(diag["senza_prezzo_o_volume"], 2)
        self.assertEqual(diag["classificabili"], 1)

    def test_ripiego_sul_volume_medio_se_manca_quello_del_giorno(self):
        rows = [{"symbol": "A", "price": 10, "volume": None, "avg_volume_3m": 1_000_000}]
        kept, _ = rank_by_dollar_volume(rows, 5)
        self.assertEqual(kept[0]["dollar_volume"], 10_000_000)

    def test_taglia_a_top_n(self):
        rows = [{"symbol": f"S{i}", "price": 10, "volume": i * 1000} for i in range(1, 30)]
        kept, diag = rank_by_dollar_volume(rows, 5)
        self.assertEqual(len(kept), 5)
        self.assertEqual(kept[0]["symbol"], "S29")      # il piu' scambiato
        self.assertEqual(diag["tenuti"], 5)

    def test_build_offline_e_cache(self):
        import tempfile
        cfg = load_config(DEMO_CFG)
        cfg["universe"]["top_n"] = 5
        cache = Cache(tempfile.mkdtemp())
        quiet = lambda *a, **k: None

        t1, d1 = build_universe(cfg, LocalProvider(cfg), cache=cache, log=quiet)
        self.assertEqual(len(t1), 5)
        self.assertEqual(d1["fonte_bacino"], "universe.source=file")

        # la seconda chiamata deve arrivare dalla cache, identica
        t2, _ = build_universe(cfg, LocalProvider(cfg), cache=cache, log=quiet)
        self.assertEqual(t1, t2)
        self.assertEqual(cache.stats().get("universe"), 1)

        # --refresh la ricalcola
        t3, _ = build_universe(cfg, LocalProvider(cfg), cache=cache, log=quiet, refresh=True)
        self.assertEqual(t1, t3)

    def test_bacino_vuoto_errore_esplicito(self):
        class Vuoto:
            name = "vuoto"
            def universe(self, cfg): return []
            def fetch_quotes(self, t, log=print): return []
        with self.assertRaises(RuntimeError):
            build_universe({"universe": {"source": "tickers"}}, Vuoto(),
                           cache=Cache(".", enabled=False), log=lambda *a, **k: None)


class TestUnioneQuoteFondamentali(unittest.TestCase):
    """La quota del giorno deve SEMPRE vincere sul fondamentale in cache."""

    def _provider(self, quotes, funds):
        p = YahooProvider(pause=0, cache=Cache(".", enabled=False))
        p.fetch_quotes = lambda t, log=print: quotes
        p.fetch_fundamentals = lambda t, log=print: funds
        return p

    def test_il_prezzo_di_oggi_sovrascrive_quello_in_cache(self):
        p = self._provider(
            quotes=[{"symbol": "A", "price": 200.0, "volume": 5_000_000}],
            funds=[{"symbol": "A", "price": 100.0, "pe_trailing": 20.0, "roe": 0.3}],
        )
        row = p.fetch(["A"])[0]
        self.assertEqual(row["price"], 200.0)      # quota
        self.assertEqual(row["pe_trailing"], 20.0)  # fondamentale conservato
        self.assertEqual(row["roe"], 0.3)

    def test_una_quota_vuota_non_cancella_il_fondamentale(self):
        p = self._provider(
            quotes=[{"symbol": "A", "price": None}],
            funds=[{"symbol": "A", "price": 100.0, "market_cap": 1e9}],
        )
        row = p.fetch(["A"])[0]
        self.assertEqual(row["price"], 100.0)
        self.assertEqual(row["market_cap"], 1e9)

    def test_una_quota_completa_porta_la_variazione_di_seduta(self):
        """
        Il difetto che ha pubblicato la variazione di ieri accanto al prezzo
        di oggi: la riga leggera del bacino (senza change_pct) finiva nella
        stessa cache di quella completa e veniva riletta come se lo fosse.
        Le due cache ora sono separate; questo test tiene fermo il confine.
        """
        from engine.providers.yahoo import QUOTE_KEYS
        self.assertIn("change_pct", QUOTE_KEYS,
                      "la variazione di seduta deve arrivare dalle quote, "
                      "non dai fondamentali: quelli scadono in sette giorni")

    def test_bacino_e_quote_complete_non_condividono_la_cache(self):
        import inspect
        from engine.providers.yahoo import YahooProvider
        sorgente = inspect.getsource(YahooProvider.fetch_quotes)
        self.assertIn("quote_veloce", sorgente,
                      "le quote leggere del bacino devono avere una cache propria")
        firma = inspect.signature(YahooProvider.fetch_quotes)
        self.assertIn("completo", firma.parameters)
        self.assertTrue(firma.parameters["completo"].default,
                        "senza dirlo esplicitamente si deve ottenere il dato completo")

    def test_quote_keys_esistono_nel_catalogo(self):
        for k in QUOTE_KEYS:
            self.assertIn(k, BY_KEY, f"QUOTE_KEYS contiene {k!r} che non e' nel catalogo")

    def test_percentuali_normalizzate_a_frazione(self):
        """
        Le unita' di Yahoo, verificate con doctor e confrontando prezzo e
        chiusura precedente: i margini e i rendimenti arrivano in FRAZIONE,
        la variazione di seduta in PUNTI PERCENTUALI. Solo la seconda si divide.
        """
        r = normalize_percent_fields({"roe": 1.4875, "net_margin": 0.24, "change_pct": -1.10617})
        self.assertAlmostEqual(r["roe"], 1.4875)        # 148,75%: frazione, intatta
        self.assertAlmostEqual(r["net_margin"], 0.24)   # frazione, intatta
        self.assertAlmostEqual(r["change_pct"], -0.0110617)   # -1,106% di seduta

    def test_variazione_di_seduta_piccola_non_resta_in_punti(self):
        """Il caso che l'euristica sbagliava: -1,1% mostrato come -110%."""
        r = normalize_percent_fields({"change_pct": -1.10617})
        self.assertLess(abs(r["change_pct"]), 0.05)

    def test_titolo_raddoppiato_in_un_anno_non_viene_diviso_per_cento(self):
        """L'altro lato dell'euristica: +160% in 12 mesi non e' +1,6%."""
        r = normalize_percent_fields({"week52_change": 1.6})
        self.assertAlmostEqual(r["week52_change"], 1.6)


class TestPesiNelConfig(unittest.TestCase):
    """L'editor dei pesi deve poter riscrivere il config senza distruggerlo."""

    def setUp(self):
        import shutil, tempfile
        self.f = Path(tempfile.mkdtemp()) / "scoring.yml"
        shutil.copy(ROOT / "config" / "scoring.yml", self.f)

    def test_legge_solo_i_pesi_attivi(self):
        from engine.weights import read_weights
        pesi = read_weights(self.f)
        self.assertIn("ev_ebitda", pesi)
        self.assertNotIn("roic", pesi)        # nel file e' commentato
        self.assertNotIn("week52_change", pesi)
        self.assertTrue(all(v > 0 for v in pesi.values()))

    def test_i_commenti_sopravvivono_al_salvataggio(self):
        from engine.weights import read_weights, write_weights
        prima = self.f.read_text(encoding="utf-8")
        pesi = read_weights(self.f)
        pesi["ev_ebitda"] = 0.25
        write_weights(self.f, pesi)
        dopo = self.f.read_text(encoding="utf-8")
        # ogni riga di commento del file originale deve esserci ancora
        for riga in prima.splitlines():
            if riga.strip().startswith("#") and "roic" not in riga:
                self.assertIn(riga, dopo, f"commento perso: {riga!r}")
        self.assertEqual(read_weights(self.f)["ev_ebitda"], 0.25)

    def test_un_peso_rimosso_viene_commentato_non_cancellato(self):
        from engine.weights import read_weights, write_weights
        pesi = read_weights(self.f)
        del pesi["current_ratio"]
        d = write_weights(self.f, pesi)
        self.assertIn("current_ratio", d["disattivati"])
        self.assertNotIn("current_ratio", read_weights(self.f))
        self.assertIn("current_ratio", self.f.read_text(encoding="utf-8"))  # la riga c'e' ancora

    def test_riattiva_una_riga_commentata_al_suo_posto(self):
        from engine.weights import read_weights, write_weights
        pesi = read_weights(self.f)
        pesi["roic"] = 0.11
        write_weights(self.f, pesi)
        self.assertEqual(read_weights(self.f)["roic"], 0.11)
        # non deve essere finita in fondo: era gia' nel blocco, commentata
        righe = [r for r in self.f.read_text(encoding="utf-8").splitlines() if "roic" in r]
        self.assertTrue(any(r.strip().startswith("roic:") for r in righe))

    def test_un_peso_nuovo_viene_aggiunto(self):
        from engine.weights import read_weights, write_weights
        pesi = read_weights(self.f)
        pesi["pb"] = 0.05
        d = write_weights(self.f, pesi)
        self.assertIn("pb", d["aggiunti"])
        self.assertEqual(read_weights(self.f)["pb"], 0.05)

    def test_rifiuta_metriche_fuori_catalogo(self):
        from engine.metrics import SCOREABLE
        from engine.weights import write_weights
        with self.assertRaises(ValueError):
            write_weights(self.f, {"inventata": 1.0}, valide=set(SCOREABLE))

    def test_rifiuta_pesi_negativi(self):
        from engine.weights import write_weights
        with self.assertRaises(ValueError):
            write_weights(self.f, {"roe": -1.0})

    def test_niente_blocco_pesi_errore_parlante(self):
        from engine.weights import read_weights
        f = self.f.with_name("altro.yml")
        f.write_text("provider: yahoo\nfilters:\n  min_price: 5\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_weights(f)

    def test_conserva_le_terminazioni_di_riga_windows(self):
        from engine.weights import read_weights, write_weights
        testo = self.f.read_text(encoding="utf-8").replace("\n", "\r\n")
        self.f.write_text(testo, encoding="utf-8", newline="")
        write_weights(self.f, {**read_weights(self.f), "roe": 0.03})
        crudo = self.f.read_bytes()
        self.assertIn(b"\r\n", crudo)
        # e nessun LF solitario: sarebbe un file con terminazioni miste
        self.assertEqual(crudo.count(b"\n"), crudo.count(b"\r\n"))


class TestPannelloValidazione(unittest.TestCase):
    """
    Il pannello esegue comandi: la validazione degli input e' la sua superficie
    di rischio, quindi va testata come tale.
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pannello", ROOT / "pannello.py")
        cls.P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.P)

    def test_nessun_comando_arbitrario(self):
        with self.assertRaises(ValueError):
            self.P.lancia("rm", {})
        with self.assertRaises(ValueError):
            self.P.lancia("run.py; rm -rf /", {})

    def test_ogni_comando_ammesso_lancia_solo_python_del_progetto(self):
        for nome, c in self.P.COMANDI.items():
            argv = c["argv"]({"tickers": "AAPL", "top": 10, "kind": ""})
            self.assertIn(argv[0], ("run.py", "-m"), f"{nome} esegue {argv[0]!r}")
            self.assertTrue(all(isinstance(a, str) for a in argv))

    def test_ticker_con_iniezione_rifiutato(self):
        for cattivo in ["AAPL; rm -rf /", "../../etc/passwd", "AA PL", "$(whoami)",
                        "AAPL|cat", "-rf", "'", "A" * 40]:
            with self.assertRaises(ValueError, msg=cattivo):
                self.P._tickers({"tickers": [cattivo]})

    def test_ticker_validi_normalizzati(self):
        self.assertEqual(self.P._tickers({"tickers": "aapl, msft; brk-b eni.mi"}),
                         ["AAPL", "MSFT", "BRK-B", "ENI.MI"])

    def test_ticker_troppo_numerosi_troncati(self):
        molti = " ".join(f"T{i}" for i in range(50))
        self.assertEqual(len(self.P._tickers({"tickers": molti})), 12)

    def test_serve_almeno_un_ticker(self):
        with self.assertRaises(ValueError):
            self.P._tickers({"tickers": "  "})

    def test_top_fuori_scala_rifiutato(self):
        self.assertEqual(self.P._top({"top": 150}), ["--top", "150"])
        self.assertEqual(self.P._top({"top": ""}), [])
        self.assertEqual(self.P._top({"top": 0}), [])       # 0 = usa il default del config
        for cattivo in (-5, 5000):
            with self.assertRaises(ValueError):
                self.P._top({"top": cattivo})
        with self.assertRaises(ValueError):
            self.P._top({"top": "molti"})

    def test_tipo_di_cache_da_lista_chiusa(self):
        self.assertEqual(self.P._kind({"kind": "quote"}), ["--clear", "quote"])
        self.assertEqual(self.P._kind({"kind": ""}), ["--clear"])
        with self.assertRaises(ValueError):
            self.P._kind({"kind": "../../"})

    def test_i_percorsi_restano_dentro_il_progetto(self):
        h = self.P.Handler.__new__(self.P.Handler)
        self.assertIsNone(h._sicuro("/../../etc/passwd"))
        self.assertIsNone(h._sicuro("/site/../../segreto"))
        self.assertIsNotNone(h._sicuro("/site/index.html"))


class TestPipelineCompleta(unittest.TestCase):
    def test_demo_end_to_end(self):
        cfg = load_config(DEMO_CFG)
        prov = LocalProvider()
        rows = prov.fetch([], {"universe": {"path": str(FIXTURE)}})
        self.assertEqual(len(rows), 23)

        add_derived(rows)
        rows, dropped = apply_filters(rows, cfg["filters"])
        self.assertEqual(sum(dropped.values()), 3)   # i tre penny stock del fixture
        self.assertTrue(all(r["price"] >= 5 for r in rows))

        res = score(rows, cfg)
        payload = build_payload(res, cfg)
        self.assertEqual(payload["rows"][0]["rank"], 1)
        # l'ordinamento è decrescente DENTRO le righe affidabili; quelle con
        # copertura insufficiente finiscono in coda anche se il punteggio è alto
        aff = [r["score"] for r in payload["rows"] if r["reliable"]]
        self.assertEqual(aff, sorted(aff, reverse=True))
        self.assertTrue(all(not r["reliable"] for r in payload["rows"][len(aff):]))
        self.assertIn("catalog", payload)
        self.assertIn("box", payload["catalog"]["metrics"][0])
        json.dumps(payload)   # deve essere serializzabile senza tipi esotici

    def test_coercizione_csv(self):
        p = ROOT / "tests" / "fixtures" / "_tmp.csv"
        p.write_text("symbol,price,pe_trailing\nAAA,12.5,\nBBB,3,18\n", encoding="utf-8")
        try:
            rows = LocalProvider().fetch([], {"universe": {"path": str(p)}})
            self.assertEqual(rows[0]["price"], 12.5)
            self.assertIsNone(rows[0]["pe_trailing"])   # cella vuota -> None, non 0
            self.assertEqual(rows[1]["pe_trailing"], 18)
        finally:
            p.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
