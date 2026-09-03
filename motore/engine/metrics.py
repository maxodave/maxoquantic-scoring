"""
Catalogo delle metriche.

QUESTO FILE È LA SINGOLA FONTE DI VERITA'.
Da qui derivano:
  * i campi che il provider deve scaricare      -> engine/providers/*
  * la direzione e la scala usate dallo scoring -> engine/scoring.py
  * i BOX ESPLICATIVI mostrati sotto ogni intestazione nel sito -> site/index.html

Aggiungere una metrica = aggiungere una voce qui. Nient'altro va toccato.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

Direction = Literal["higher_better", "lower_better", "target_band", "context"]
# higher_better  -> più alto = punteggio più alto
# lower_better   -> più basso = punteggio più alto (es. P/E, Debt/Equity)
# target_band    -> ottimale dentro una fascia, penalizzato fuori (es. Current Ratio)
# context        -> non entra nel punteggio, serve a leggere/filtrare (es. settore)


@dataclass(frozen=True)
class Box:
    """Contenuto del box informativo mostrato sotto l'intestazione della colonna."""
    cos_e: str          # che cos'è esattamente il numero
    come_si_legge: str  # come interpretarlo
    trappola: str       # l'errore classico che fa dire cose sbagliate a questo dato


@dataclass(frozen=True)
class Metric:
    key: str                       # nome canonico interno
    label: str                     # intestazione mostrata nel sito
    group: str                     # raggruppamento nel sito
    unit: str                      # "$", "%", "x", "shares", "ratio", "score", ""
    direction: Direction
    box: Box
    yahoo_info: Optional[str] = None   # chiave in yfinance Ticker.info / quoteSummary
    yahoo_screener: Optional[str] = None  # id campo nello screener Yahoo (per riferimento)
    fmt: str = "num"               # "num" | "pct" | "money" | "mult" | "int"
    band: Optional[tuple] = None   # usato solo da direction="target_band": (min_ok, max_ok)
    winsor: tuple = (0.02, 0.98)   # quantili di taglio delle code prima di normalizzare
    notes: str = ""


CATALOG: list[Metric] = [
    # ------------------------------------------------------------------ IDENTITA'
    Metric(
        key="symbol", label="Ticker", group="Identità", unit="", direction="context",
        yahoo_info="symbol", yahoo_screener="symbol", fmt="num",
        box=Box(
            cos_e="Il codice con cui il titolo è quotato su quella borsa.",
            come_si_legge="Identifica l'azione, non l'azienda: la stessa società può avere ticker diversi su borse diverse (e ADR con dati in valuta differente).",
            trappola="Confrontare un ticker USA con un ADR o una quotazione secondaria della stessa società come se fossero due aziende distinte.",
        ),
    ),
    Metric(
        key="name", label="Azienda", group="Identità", unit="", direction="context",
        yahoo_info="longName", yahoo_screener="companyshortname",
        box=Box(
            cos_e="Ragione sociale dell'emittente.",
            come_si_legge="Serve solo a leggere la tabella.",
            trappola="Nomi simili (holding vs controllata quotata) non sono la stessa entità di bilancio.",
        ),
    ),
    Metric(
        key="sector", label="Settore", group="Identità", unit="", direction="context",
        yahoo_info="sector", yahoo_screener="sector",
        box=Box(
            cos_e="Classificazione settoriale assegnata dal provider.",
            come_si_legge="È la chiave del confronto: multipli e margini hanno senso solo dentro lo stesso settore.",
            trappola="Confrontare il P/E di una utility con quello di una software company. Sono due scale diverse, non due qualità diverse.",
        ),
    ),

    # ------------------------------------------------------------------ ATTIVITA'
    Metric(
        key="volume", label="Volume", group="Attività", unit="azioni", direction="context",
        yahoo_info="regularMarketVolume", yahoo_screener="dayvolume", fmt="int",
        box=Box(
            cos_e="Il numero di AZIONI passate di mano nella seduta. Non euro, non dollari: pezzi.",
            come_si_legge="Da solo dice quasi nulla. Un titolo da 1 $ con 400 milioni di azioni scambiate muove 400 milioni di dollari; uno da 220 $ con 87 milioni ne muove 19 miliardi. Il secondo è venti volte più 'attivo', ma nella classifica per volume arriva dopo.",
            trappola="È l'errore su cui è costruita la lista 'Most Actives' di Yahoo: ordinando per volume in pezzi, senza filtri, la classifica si riempie di penny stock e società guscio con prezzo sotto il dollaro.",
        ),
        notes="Usare SEMPRE insieme a dollar_volume e rel_volume.",
    ),
    Metric(
        key="dollar_volume", label="Volume in $", group="Attività", unit="$", direction="higher_better",
        yahoo_info=None, fmt="money",
        box=Box(
            cos_e="Prezzo x volume: il denaro effettivamente scambiato nella seduta. Calcolato, non scaricato.",
            come_si_legge="È la vera misura di quanto un titolo è liquido. Sotto qualche milione di dollari al giorno una posizione istituzionale non entra e non esce senza muovere il prezzo.",
            trappola="Resta un dato di un solo giorno: una singola notizia lo gonfia. Per giudicare la liquidità strutturale confrontalo con la media a 3 mesi.",
        ),
        notes="DERIVATO: price * volume.",
    ),
    Metric(
        key="avg_volume_3m", label="Volume medio 3M", group="Attività", unit="azioni", direction="context",
        yahoo_info="averageVolume", yahoo_screener="avgdailyvol3m", fmt="int",
        box=Box(
            cos_e="Media delle azioni scambiate al giorno negli ultimi 3 mesi.",
            come_si_legge="È la 'normalità del titolo: il riferimento rispetto a cui la seduta di oggi è calma o anomala.",
            trappola="Un IPO recente o un titolo appena entrato in un indice ha una media a 3 mesi non rappresentativa.",
        ),
    ),
    Metric(
        key="rel_volume", label="Volume relativo", group="Attività", unit="x", direction="context",
        yahoo_info=None, yahoo_screener="relativevolume", fmt="mult",
        box=Box(
            cos_e="Volume di oggi diviso il volume medio. 1x = giornata normale, 5x = si scambia cinque volte il solito.",
            come_si_legge="È la metrica che 'Most Actives' avrebbe dovuto usare: normalizza per la taglia del titolo e isola l'anomalia vera. Un titolo a 33x sta reagendo a qualcosa.",
            trappola="Anomalia non significa opportunità. Un volume relativo estremo accompagna sia le trimestrali sopra le attese sia i delisting, i reverse split e le pump-and-dump.",
        ),
        notes="DERIVATO se il provider non lo espone: volume / avg_volume_3m.",
    ),

    # ------------------------------------------------------------------ TAGLIA
    Metric(
        key="market_cap", label="Capitalizzazione", group="Taglia", unit="$", direction="context",
        yahoo_info="marketCap", yahoo_screener="intradaymarketcap", fmt="money",
        box=Box(
            cos_e="Prezzo x azioni in circolazione: quanto il mercato valuta l'intero capitale azionario.",
            come_si_legge="È il filtro di igiene numero uno. Sotto ~300 M$ i dati di bilancio sono spesso incompleti, i multipli instabili e il flottante troppo sottile perché i confronti abbiano senso.",
            trappola="Non è il valore dell'azienda: ignora il debito e la cassa. Per quello serve l'Enterprise Value.",
        ),
    ),
    Metric(
        key="enterprise_value", label="Enterprise Value", group="Taglia", unit="$", direction="context",
        yahoo_info="enterpriseValue", fmt="money",
        box=Box(
            cos_e="Capitalizzazione + debito netto: quanto costerebbe comprare l'azienda intera, debiti inclusi.",
            come_si_legge="È il numeratore corretto quando confronti aziende con strutture finanziarie diverse.",
            trappola="Su banche e assicurazioni l'EV perde significato: il debito è materia prima operativa, non leva.",
        ),
    ),

    # ------------------------------------------------------------------ VALUTAZIONE
    Metric(
        key="pe_trailing", label="P/E (TTM)", group="Valutazione", unit="x", direction="lower_better",
        yahoo_info="trailingPE", yahoo_screener="peratio.lasttwelvemonths", fmt="mult",
        box=Box(
            cos_e="Prezzo diviso utile per azione degli ultimi 12 mesi: quanti anni di utili correnti stai pagando.",
            come_si_legge="Basso può voler dire sottovalutata, alto che il mercato si aspetta crescita. Ha senso solo confrontato con il settore e con la storia del titolo.",
            trappola="Se l'utile è negativo il P/E non esiste (Yahoo mostra '--'). Escludere quelle righe fa sparire dal confronto tutte le aziende in perdita: è una selezione, non un dato mancante.",
        ),
        winsor=(0.05, 0.95),
    ),
    Metric(
        key="pe_forward", label="P/E atteso", group="Valutazione", unit="x", direction="lower_better",
        yahoo_info="forwardPE", fmt="mult",
        box=Box(
            cos_e="Prezzo diviso l'utile per azione che gli analisti stimano per i prossimi 12 mesi.",
            come_si_legge="Anticipa la svolta che il P/E storico non vede ancora.",
            trappola="Non è un dato di bilancio, è un consenso di opinioni: rivedibile, e sistematicamente ottimista nelle fasi finali di un ciclo.",
        ),
        winsor=(0.05, 0.95),
    ),
    Metric(
        key="pb", label="P/B", group="Valutazione", unit="x", direction="lower_better",
        yahoo_info="priceToBook", yahoo_screener="pricebookratio.quarterly", fmt="mult",
        box=Box(
            cos_e="Prezzo diviso patrimonio netto contabile per azione.",
            come_si_legge="Utile dove gli attivi sono reali e valutabili: banche, immobiliare, industria pesante.",
            trappola="Su software e servizi è quasi inutile: il valore sta in marchi, codice e persone, che in bilancio non ci sono. Un P/B di 30 non è una bolla, è un bilancio senza fabbriche.",
        ),
    ),
    Metric(
        key="ps", label="P/S", group="Valutazione", unit="x", direction="lower_better",
        yahoo_info="priceToSalesTrailing12Months", fmt="mult",
        box=Box(
            cos_e="Capitalizzazione diviso il fatturato degli ultimi 12 mesi.",
            come_si_legge="Funziona quando l'utile non c'è ancora ma il fatturato sì, tipicamente aziende in crescita.",
            trappola="Ignora completamente se quel fatturato produce margine. Un P/S basso su un business al 3% di margine netto non è un affare.",
        ),
    ),
    Metric(
        key="ev_ebitda", label="EV/EBITDA", group="Valutazione", unit="x", direction="lower_better",
        yahoo_info="enterpriseToEbitda", yahoo_screener="lastclosetevebitda.lasttwelvemonths", fmt="mult",
        box=Box(
            cos_e="Enterprise Value diviso EBITDA: il multiplo che usa chi compra aziende intere.",
            come_si_legge="Il più confrontabile fra i multipli, perché neutralizza leva finanziaria, fiscalità e politiche di ammortamento.",
            trappola="L'EBITDA non è cassa: esclude gli investimenti. Un'azienda capital-intensive può avere un EV/EBITDA attraente e flusso di cassa libero nullo.",
        ),
    ),
    Metric(
        key="ev_sales", label="EV/Sales", group="Valutazione", unit="x", direction="lower_better",
        yahoo_info="enterpriseToRevenue", yahoo_screener="lastclosetevtotalrevenue.lasttwelvemonths", fmt="mult",
        box=Box(
            cos_e="Enterprise Value diviso fatturato.",
            come_si_legge="Il multiplo di ripiego quando EBITDA e utile sono negativi.",
            trappola="Confrontabile solo a parità di marginalità attesa.",
        ),
    ),
    Metric(
        key="peg", label="PEG", group="Valutazione", unit="x", direction="lower_better",
        yahoo_info="pegRatio", fmt="mult",
        box=Box(
            cos_e="P/E diviso il tasso di crescita atteso degli utili. Sotto 1 = crescita pagata poco.",
            come_si_legge="Tenta di rispondere alla domanda giusta: quel P/E alto è giustificato dalla crescita?",
            trappola="Eredita l'incertezza della stima di crescita al denominatore, quindi è il più fragile dei multipli. Con crescita vicina a zero il PEG esplode.",
        ),
        winsor=(0.05, 0.95),
    ),

    # ------------------------------------------------------------------ REDDITIVITA'
    Metric(
        key="gross_margin", label="Margine lordo", group="Redditività", unit="%", direction="higher_better",
        yahoo_info="grossMargins", yahoo_screener="grossprofitmargin.lasttwelvemonths", fmt="pct",
        box=Box(
            cos_e="Quanto resta di ogni euro di fatturato dopo il costo diretto del venduto.",
            come_si_legge="È il miglior indizio di potere di prezzo: margini lordi alti e stabili nel tempo sono il segno di un vantaggio competitivo difendibile.",
            trappola="Il livello assoluto è settoriale (distribuzione 20%, software 80%). Conta il confronto con i concorrenti e la tendenza, non il numero.",
        ),
    ),
    Metric(
        key="net_margin", label="Margine netto", group="Redditività", unit="%", direction="higher_better",
        yahoo_info="profitMargins", yahoo_screener="netincomemargin.lasttwelvemonths", fmt="pct",
        box=Box(
            cos_e="Utile netto diviso fatturato: quanto resta davvero in fondo al conto economico.",
            come_si_legge="Sintetizza in un numero efficienza operativa, costo del debito e fiscalità.",
            trappola="È la riga più sporca del bilancio: plusvalenze da cessioni, svalutazioni e poste fiscali una tantum la distorcono. Guarda tre anni, non uno.",
        ),
    ),
    Metric(
        key="roe", label="ROE", group="Redditività", unit="%", direction="higher_better",
        yahoo_info="returnOnEquity", yahoo_screener="returnonequity.lasttwelvemonths", fmt="pct",
        box=Box(
            cos_e="Utile netto diviso patrimonio netto: quanto rende il capitale degli azionisti.",
            come_si_legge="Sopra il 15% sostenuto per anni indica un business che compone valore.",
            trappola="Si alza anche riducendo il denominatore. Debito e buyback aggressivi gonfiano il ROE senza migliorare l'azienda: con patrimonio netto negativo il numero diventa privo di senso. Leggilo sempre accanto a Debt/Equity e ROIC.",
        ),
    ),
    Metric(
        key="roa", label="ROA", group="Redditività", unit="%", direction="higher_better",
        yahoo_info="returnOnAssets", yahoo_screener="returnonassets.lasttwelvemonths", fmt="pct",
        box=Box(
            cos_e="Utile diviso totale attivo: quanto rende tutto il capitale impiegato, non solo quello degli azionisti.",
            come_si_legge="Immune al trucco della leva: è il controllo naturale del ROE.",
            trappola="Penalizza strutturalmente i settori ad alta intensità di capitale. Confronta solo dentro il settore.",
        ),
    ),
    Metric(
        key="roic", label="ROIC", group="Redditività", unit="%", direction="higher_better",
        yahoo_info=None, yahoo_screener="returnontotalcapital.lasttwelvemonths", fmt="pct",
        box=Box(
            cos_e="Rendimento sul capitale investito operativo (debito + equity al netto della cassa).",
            come_si_legge="La misura più onesta di qualità del business. Il confronto che conta è con il costo del capitale: ROIC > WACC significa che l'azienda crea valore crescendo, altrimenti lo distrugge.",
            trappola="Definizioni diverse fra provider: non mischiare ROIC di fonti differenti nella stessa classifica.",
        ),
    ),

    # ------------------------------------------------------------------ CRESCITA
    Metric(
        key="revenue_growth", label="Crescita fatturato", group="Crescita", unit="%", direction="higher_better",
        yahoo_info="revenueGrowth", yahoo_screener="quarterlyrevenuegrowth.quarterly", fmt="pct",
        box=Box(
            cos_e="Variazione del fatturato rispetto allo stesso periodo dell'anno prima.",
            come_si_legge="Anno su anno, non trimestre su trimestre: neutralizza la stagionalità.",
            trappola="Non distingue crescita organica da acquisizioni. Un +40% da shopping societario è un altro business rispetto a un +40% a perimetro costante.",
        ),
    ),
    Metric(
        key="earnings_growth", label="Crescita utili", group="Crescita", unit="%", direction="higher_better",
        yahoo_info="earningsGrowth", yahoo_screener="epsgrowth.lasttwelvemonths", fmt="pct",
        box=Box(
            cos_e="Variazione dell'utile per azione anno su anno.",
            come_si_legge="Se cresce più del fatturato, la leva operativa sta funzionando.",
            trappola="Partendo da una base minuscola produce percentuali assurde (+2000%) che dominano qualunque classifica. Va sempre winsorizzata o convertita in percentile.",
        ),
        winsor=(0.05, 0.95),
    ),

    # ------------------------------------------------------------------ SOLIDITA'
    Metric(
        key="debt_to_equity", label="Debt/Equity", group="Solidità", unit="%", direction="lower_better",
        yahoo_info="debtToEquity", yahoo_screener="totaldebtequity.lasttwelvemonths", fmt="num",
        box=Box(
            cos_e="Debito totale diviso patrimonio netto. Yahoo lo espone in percentuale: 150 = 1,5x.",
            come_si_legge="Misura quanta della redditività è comprata a debito. Sopra 200% in un settore ciclico è fragilità.",
            trappola="Un valore basso non è automaticamente virtù: può segnalare un'azienda che non trova progetti in cui investire.",
        ),
    ),
    Metric(
        key="current_ratio", label="Current Ratio", group="Solidità", unit="x", direction="target_band",
        yahoo_info="currentRatio", yahoo_screener="currentratio.lasttwelvemonths", fmt="mult",
        band=(1.2, 3.0),
        box=Box(
            cos_e="Attivo corrente diviso passivo corrente: la capacità di coprire i debiti a 12 mesi.",
            come_si_legge="La fascia sana è circa 1,2-3. Sotto 1 c'è tensione di liquidità.",
            trappola="Non è 'più alto meglio è. Un 8x significa montagne di cassa e magazzino ferme e non impiegate: per questo qui il punteggio premia una fascia, non il massimo.",
        ),
    ),
    Metric(
        key="total_cash", label="Cassa", group="Solidità", unit="$", direction="context",
        yahoo_info="totalCash", fmt="money",
        box=Box(
            cos_e="Cassa e equivalenti a bilancio.",
            come_si_legge="Da leggere sempre in rapporto al debito e al consumo di cassa, non in valore assoluto.",
            trappola="Cassa lorda alta con debito ancora più alto non è solidità. Serve il debito netto.",
        ),
    ),
    Metric(
        key="total_debt", label="Debito totale", group="Solidità", unit="$", direction="context",
        yahoo_info="totalDebt", fmt="money",
        box=Box(
            cos_e="Debito finanziario complessivo, a breve e a lungo termine.",
            come_si_legge="Il numero che conta è debito netto / EBITDA: sopra 3-4x lo spazio di manovra si chiude.",
            trappola="Il valore assoluto non dice niente senza la taglia dell'azienda e la stabilità dei suoi flussi.",
        ),
    ),

    # ------------------------------------------------------------------ CASSA
    Metric(
        key="fcf", label="Free Cash Flow", group="Cassa", unit="$", direction="higher_better",
        yahoo_info="freeCashflow", yahoo_screener="leveredfreecashflow.lasttwelvemonths", fmt="money",
        box=Box(
            cos_e="Cassa generata dall'attività operativa meno gli investimenti necessari a mantenerla.",
            come_si_legge="È il denaro davvero disponibile per dividendi, buyback, debito e acquisizioni. L'utile è un'opinione contabile, questo è un fatto bancario.",
            trappola="Può essere gonfiato tagliando investimenti o allungando i pagamenti ai fornitori: entrambi comprano cassa oggi contro competitività domani.",
        ),
    ),
    Metric(
        key="fcf_yield", label="FCF Yield", group="Cassa", unit="%", direction="higher_better",
        yahoo_info=None, fmt="pct",
        box=Box(
            cos_e="Free cash flow diviso capitalizzazione: il rendimento in cassa che l'azienda produce al prezzo di oggi.",
            come_si_legge="Confrontabile diretto con il rendimento di un titolo di stato: è il ponte fra qualità del business e prezzo pagato.",
            trappola="Rendimenti a due cifre sono quasi sempre un avvertimento, non un regalo: il mercato sta prezzando che quella cassa non si ripeterà.",
        ),
        notes="DERIVATO: fcf / market_cap.",
    ),
    Metric(
        key="operating_cashflow", label="Cash flow operativo", group="Cassa", unit="$", direction="higher_better",
        yahoo_info="operatingCashflow", fmt="money",
        box=Box(
            cos_e="Cassa prodotta dalla gestione corrente, prima degli investimenti.",
            come_si_legge="Confrontalo con l'utile netto: se l'utile cresce e questo no, la qualità degli utili si sta deteriorando.",
            trappola="Un solo esercizio non basta, i cicli di magazzino e crediti lo fanno oscillare.",
        ),
    ),

    # ------------------------------------------------------------------ MERCATO
    Metric(
        key="price", label="Prezzo", group="Mercato", unit="$", direction="context",
        yahoo_info="regularMarketPrice", yahoo_screener="intradayprice", fmt="money",
        box=Box(
            cos_e="Ultimo prezzo battuto.",
            come_si_legge="Nessuna informazione sul valore: un titolo da 3 $ non è 'economico'. Il prezzo conta solo dentro un rapporto.",
            trappola="Prezzi molto bassi (sotto 1-5 $) sono la firma dei penny stock. Un filtro di prezzo minimo è il modo più rapido di ripulire un universo.",
        ),
    ),
    Metric(
        key="change_pct", label="Variazione %", group="Mercato", unit="%", direction="context",
        yahoo_info="regularMarketChangePercent", yahoo_screener="percentchange", fmt="pct",
        box=Box(
            cos_e="Variazione percentuale del prezzo nella seduta.",
            come_si_legge="Rumore, nel 95% dei casi. Diventa informazione solo insieme a un volume relativo alto.",
            trappola="Su titoli illiquidi una singola operazione minima produce -50% o +90%. Nella lista Yahoo senza filtri si vedono esattamente questi valori.",
        ),
    ),
    Metric(
        key="change_abs", label="Variazione", group="Mercato", unit="$", direction="context",
        yahoo_info=None, fmt="num",
        box=Box(
            cos_e="Quanti dollari ha guadagnato o perso il titolo nella seduta. Calcolato dal prezzo e dalla variazione percentuale, non scaricato.",
            come_si_legge="È la colonna 'Change' degli screener. Serve solo a leggere la percentuale in valore assoluto: 2 $ su 20 $ e 2 $ su 400 $ sono due cose diverse.",
            trappola="Confrontare la variazione in dollari fra titoli con prezzi molto diversi non dice niente: la percentuale è l'unica grandezza confrontabile.",
        ),
        notes="DERIVATO: price * change_pct / (1 + change_pct), cioè prezzo meno chiusura precedente.",
    ),
    Metric(
        key="premarket_price", label="Prezzo pre-mercato", group="Mercato", unit="$",
        direction="context", yahoo_info="preMarketPrice", fmt="money",
        box=Box(
            cos_e="L'ultimo prezzo scambiato nelle contrattazioni che precedono l'apertura (dalle 4:00 alle 9:30 di New York).",
            come_si_legge="Dice come il mercato sta reagendo a quello che è successo dopo la chiusura di ieri: trimestrali, notizie societarie, dati macro usciti al mattino.",
            trappola="È un mercato sottile: pochi scambi bastano a muovere il prezzo, e l'apertura ufficiale spesso cancella metà del movimento. Non è il prezzo a cui comprerai.",
        ),
        notes="Disponibile solo a mercato chiuso e pre-apertura. Yahoo NON espone il volume pre-mercato.",
    ),
    Metric(
        key="premarket_change_pct", label="Variazione pre-mercato", group="Mercato", unit="%",
        direction="context", yahoo_info="preMarketChangePercent", fmt="pct",
        box=Box(
            cos_e="Di quanto il prezzo pre-mercato si discosta dalla chiusura precedente.",
            come_si_legge="È il numero che si guarda al mattino: quali titoli aprono lontano da dove hanno chiuso, e di quanto.",
            trappola="Senza il volume — che Yahoo non pubblica per il pre-mercato — non si può sapere se quel movimento sia sostenuto da scambi veri o da poche operazioni.",
        ),
    ),
    Metric(
        key="week52_low", label="Minimo 52W", group="Mercato", unit="$", direction="context",
        yahoo_info="fiftyTwoWeekLow", yahoo_screener="fiftytwowklow", fmt="num",
        box=Box(
            cos_e="Il prezzo più basso toccato negli ultimi dodici mesi.",
            come_si_legge="Insieme al massimo delimita l'intervallo in cui il titolo si è mosso: dice dove sta oggi il prezzo dentro il suo anno.",
            trappola="Non è un pavimento. Un titolo può stare sul minimo di 52 settimane ed essere ancora caro rispetto agli utili.",
        ),
    ),
    Metric(
        key="week52_high", label="Massimo 52W", group="Mercato", unit="$", direction="context",
        yahoo_info="fiftyTwoWeekHigh", yahoo_screener="fiftytwowkhigh", fmt="num",
        box=Box(
            cos_e="Il prezzo più alto toccato negli ultimi dodici mesi.",
            come_si_legge="Con il minimo forma l'intervallo dell'anno. Un prezzo appiccicato al massimo segnala un titolo in tendenza, non un titolo caro o conveniente.",
            trappola="Confrontare due titoli sulla distanza dal massimo non dice niente sulla loro qualità: è una misura di momentum, non di azienda.",
        ),
    ),
    Metric(
        key="week52_position", label="Posizione nell'intervallo 52W", group="Mercato", unit="%",
        direction="context", yahoo_info=None, fmt="pct",
        box=Box(
            cos_e="Dove sta il prezzo di oggi fra il minimo e il massimo dei dodici mesi: 0% sul minimo, 100% sul massimo. Calcolato, non scaricato.",
            come_si_legge="È la colonna «52 Week Range» degli screener, ridotta a un numero. Serve a leggere l'intervallo senza confrontare tre cifre a mente.",
            trappola="Un intervallo largo e uno stretto danno lo stesso 50%: guarda sempre anche quanto distano minimo e massimo.",
        ),
        notes="DERIVATO: (prezzo - minimo) / (massimo - minimo).",
    ),
    Metric(
        key="week52_change", label="Variazione 52W", group="Mercato", unit="%", direction="context",
        yahoo_info="52WeekChange", yahoo_screener="fiftytwowkpercentchange", fmt="pct",
        box=Box(
            cos_e="Rendimento del prezzo negli ultimi dodici mesi.",
            come_si_legge="Momentum. Storicamente ha potere predittivo su 6-12 mesi, e si inverte bruscamente ai punti di svolta del ciclo.",
            trappola="In un motore di valutazione va pesato poco o tenuto separato: è l'unica metrica che misura il consenso invece dell'azienda.",
        ),
    ),
    Metric(
        key="beta", label="Beta (5Y)", group="Mercato", unit="x", direction="context",
        yahoo_info="beta", yahoo_screener="beta", fmt="mult",
        box=Box(
            cos_e="Sensibilità storica del titolo ai movimenti dell'indice. 1 = si muove come il mercato.",
            come_si_legge="Serve a dimensionare il rischio del portafoglio, non a giudicare l'azienda.",
            trappola="È retrospettivo e instabile: cambia con la finestra di calcolo. Su titoli poco liquidi è sottostimato per costruzione.",
        ),
    ),

    # ------------------------------------------------------------------ OUTPUT
    Metric(
        key="score", label="Punteggio", group="Punteggio", unit="/100", direction="higher_better",
        yahoo_info=None, fmt="num",
        box=Box(
            cos_e="Media pesata dei percentili delle metriche selezionate, riportata su scala 0-100. I pesi stanno in config/scoring.yml.",
            come_si_legge="È un ordinamento RELATIVO all'universo analizzato, non un giudizio assoluto: 80/100 significa 'meglio dell'80% dei titoli in questa lista', non 'buon investimento'.",
            trappola="Cambiare l'universo cambia tutti i punteggi senza che nessun bilancio sia cambiato. Il punteggio va sempre pubblicato insieme all'universo e alla data che lo hanno prodotto.",
        ),
    ),
    Metric(
        key="coverage", label="Copertura dati", group="Punteggio", unit="%", direction="higher_better",
        yahoo_info=None, fmt="pct",
        box=Box(
            cos_e="Quota di metriche pesate effettivamente disponibili per quella riga.",
            come_si_legge="Il controllo di affidabilità del punteggio. Sotto il 60% il numero è costruito su troppi buchi.",
            trappola="Senza questa colonna un'azienda con tre metriche su dodici sembra confrontabile con una completa. È il difetto silenzioso di quasi tutti gli screener.",
        ),
    ),
]

BY_KEY: dict[str, Metric] = {m.key: m for m in CATALOG}

# metriche che il motore calcola invece di scaricare
DERIVED = {"dollar_volume", "rel_volume", "fcf_yield", "change_abs",
           "week52_position", "score", "coverage"}

# metriche candidate a entrare nel punteggio (tutto ciò che non è "context")
SCOREABLE = [m.key for m in CATALOG if m.direction != "context" and m.key not in {"score", "coverage"}]

GROUPS = list(dict.fromkeys(m.group for m in CATALOG))


def provider_fields() -> dict[str, str]:
    """Mappa chiave canonica -> campo del provider, per le metriche scaricabili."""
    return {m.key: m.yahoo_info for m in CATALOG if m.yahoo_info}


def to_json_dict() -> dict:
    """
    Serializza il catalogo per il frontend (alimenta i box del sito).

    Ogni metrica porta con se' anche la propria traduzione inglese, quando
    esiste: cosi' il selettore di lingua della pagina non deve chiedere niente
    a nessuno, e una metrica non ancora tradotta resta semplicemente in
    italiano invece di sparire.
    """
    from .i18n_en import GROUPS as GROUPS_EN, METRICS as METRICS_EN

    metriche = []
    for m in CATALOG:
        voce = {
            **{k: v for k, v in asdict(m).items() if k not in {"box", "winsor"}},
            "box": asdict(m.box),
        }
        tr = METRICS_EN.get(m.key)
        if tr:
            voce["en"] = {"label": tr[0],
                          "box": {"cos_e": tr[1], "come_si_legge": tr[2], "trappola": tr[3]}}
        metriche.append(voce)

    return {
        "groups": GROUPS,
        "groups_en": [GROUPS_EN.get(g, g) for g in GROUPS],
        "metrics": metriche,
    }
