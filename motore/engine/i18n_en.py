"""
Traduzione inglese del catalogo (engine/metrics.py).

Sta in un file separato per due motivi. Il primo: metrics.py resta leggibile,
con la definizione di ogni metrica in una schermata invece che in tre. Il
secondo: una traduzione si rilegge tutta insieme, e qui e' tutta insieme.

Chiavi mancanti = si ricade sull'italiano, non si rompe niente. Aggiungere una
metrica al catalogo senza tradurla e' quindi lecito: comparira' in italiano
anche in inglese, finche' non la si scrive qui.
"""
from __future__ import annotations

GROUPS: dict[str, str] = {
    "Identità": "Identity",
    "Attività": "Activity",
    "Taglia": "Size",
    "Valutazione": "Valuation",
    "Redditività": "Profitability",
    "Crescita": "Growth",
    "Solidità": "Balance sheet",
    "Cassa": "Cash",
    "Mercato": "Market",
    "Punteggio": "Score",
}

DIRECTIONS: dict[str, str] = {
    "higher_better": "higher is better",
    "lower_better": "lower is better",
    "target_band": "a band is rewarded, not the maximum",
    "context": "context only, not part of the score",
}

# key -> (label, cos_e, come_si_legge, trappola)
METRICS: dict[str, tuple[str, str, str, str]] = {
    "symbol": (
        "Ticker",
        "The code the stock trades under on that exchange.",
        "It identifies the share, not the company: the same business can trade under different tickers on different exchanges (and ADRs report in another currency).",
        "Treating a US ticker and an ADR of the same company as two separate businesses.",
    ),
    "name": (
        "Company",
        "The issuer's legal name.",
        "Useful for reading the table, never for matching data: names change, tickers are the reliable key.",
        "Two companies with near-identical names are a classic source of mixed-up data.",
    ),
    "sector": (
        "Sector",
        "The industry classification the provider assigns.",
        "It is the comparison group: multiples only mean something against similar companies.",
        "Classifications disagree between providers, and conglomerates end up somewhere arbitrary.",
    ),
    "volume": (
        "Volume",
        "The number of SHARES that changed hands in the session. Not euros, not dollars: pieces.",
        "On its own it says almost nothing. A $1 stock trading 400 million shares moves $400 million; a $220 stock trading 87 million moves $19 billion. The second is twenty times more 'active' — and ranks below the first.",
        "This is the mistake Yahoo's 'Most Actives' list is built on: sorting by share count, with no filters, fills the ranking with penny stocks and shell companies priced under a dollar.",
    ),
    "dollar_volume": (
        "Dollar volume",
        "Price × volume: the money actually traded in the session. Computed, not downloaded.",
        "This is the real measure of liquidity. Below a few million dollars a day an institutional position cannot get in or out without moving the price.",
        "It is still a single day: one piece of news inflates it. For structural liquidity, compare it with the 3-month average.",
    ),
    "avg_volume_3m": (
        "Avg volume 3M",
        "Average shares traded per day over the last three months.",
        "It is the stock's 'normal': the yardstick that makes today either quiet or unusual.",
        "A recent IPO, or a stock that just entered an index, has a 3-month average that means nothing yet.",
    ),
    "rel_volume": (
        "Relative volume",
        "Today's volume divided by the 3-month average. Computed, not downloaded.",
        "This is the true activity measure: 30× on a small stock is a genuine anomaly, 4× on a large one is heavy trading, 1× is an ordinary day. Yahoo has this column but does not sort on it.",
        "A high value says something happened, not what: earnings, an index rebalance and a rumour all look identical here.",
    ),
    "market_cap": (
        "Market cap",
        "Share price times shares outstanding: what the market says the equity is worth.",
        "It sets the peer group. Comparing multiples across size classes is comparing different businesses.",
        "It ignores debt. Two companies with the same market cap and very different debt loads are not equally expensive — that is what enterprise value is for.",
    ),
    "enterprise_value": (
        "Enterprise value",
        "Market cap plus net debt: what it would cost to buy the whole business, debt included.",
        "It is the numerator of the multiples that survive a leveraged balance sheet (EV/EBITDA, EV/Sales).",
        "Net cash makes it smaller than market cap, which is correct and still surprises people.",
    ),
    "pe_trailing": (
        "P/E (TTM)",
        "Price divided by earnings per share of the last twelve months.",
        "How many years of current earnings you are paying for. Low is cheap only if those earnings repeat.",
        "One extraordinary item — an asset sale, a write-down — distorts it completely. And it is meaningless when earnings are negative.",
    ),
    "pe_forward": (
        "Forward P/E",
        "Price divided by analysts' expected earnings.",
        "It looks ahead instead of behind, which is what you want when a business is changing.",
        "It is an estimate, and estimates are systematically optimistic. It also disappears the moment coverage thins out.",
    ),
    "pb": (
        "P/B",
        "Price divided by book value of equity.",
        "It works for banks and asset-heavy businesses, where book value means something.",
        "For software or services it is close to noise: their real assets — people, code, brand — are not on the balance sheet.",
    ),
    "ps": (
        "P/S",
        "Price divided by revenue per share.",
        "It survives where earnings do not: young companies, cyclical troughs.",
        "It ignores whether that revenue makes money. Two companies with the same P/S and opposite margins are not comparable.",
    ),
    "ev_ebitda": (
        "EV/EBITDA",
        "Enterprise value over earnings before interest, taxes, depreciation and amortisation.",
        "The workhorse multiple for comparing companies with different debt and tax situations.",
        "EBITDA is not cash: it excludes the capital spending that capital-intensive businesses cannot avoid.",
    ),
    "ev_sales": (
        "EV/Sales",
        "Enterprise value over revenue.",
        "Same purpose as P/S but debt-aware. Useful when there are no earnings yet.",
        "Same blindness as P/S: revenue quality is invisible here.",
    ),
    "peg": (
        "PEG",
        "P/E divided by the expected earnings growth rate.",
        "An attempt to say whether a high multiple is justified by growth.",
        "It multiplies two uncertain numbers, one of which is a forecast. Treat it as a hint, never as a verdict.",
    ),
    "gross_margin": (
        "Gross margin",
        "Revenue minus cost of goods sold, over revenue.",
        "It measures pricing power: how much of every euro of sales survives the cost of producing it.",
        "Companies book costs differently between 'cost of goods' and 'operating expenses', so cross-company comparisons need the same industry.",
    ),
    "net_margin": (
        "Net margin",
        "Net income over revenue: what is left at the very bottom.",
        "The most complete profitability measure, and the easiest to read.",
        "It is also the one most affected by one-off items and by taxes, which say more about jurisdiction than about the business.",
    ),
    "roe": (
        "ROE",
        "Net income over shareholders' equity.",
        "How much profit management extracts from the capital shareholders left in the business.",
        "Debt inflates it: a company can raise ROE simply by borrowing. Always read it next to debt/equity.",
    ),
    "roa": (
        "ROA",
        "Net income over total assets.",
        "The debt-insensitive cousin of ROE: it measures the return on everything the company uses, however financed.",
        "It penalises asset-heavy businesses by construction, so it only compares within an industry.",
    ),
    "roic": (
        "ROIC",
        "Operating profit after tax over invested capital.",
        "The cleanest measure of whether a business creates value: compare it with the cost of that capital.",
        "Yahoo's unofficial API does not return it per stock — it only exists as a screener column — so here it is usually empty.",
    ),
    "revenue_growth": (
        "Revenue growth",
        "Change in revenue over the last twelve months.",
        "The first thing to look at: without growing revenue, margin improvements eventually run out.",
        "From a tiny base, +2000% means nothing. This is why the engine trims the tails before ranking.",
    ),
    "earnings_growth": (
        "Earnings growth",
        "Change in earnings over the last twelve months.",
        "Faster than revenue means operating leverage; slower means costs are winning.",
        "Around zero it explodes: going from 1 to 2 million is +100% and is not news.",
    ),
    "debt_to_equity": (
        "Debt/Equity",
        "Total debt over shareholders' equity.",
        "How much of the business is financed by lenders rather than owners. It is the fragility gauge.",
        "'Right' depends entirely on the industry: a utility carries debt a software company never could.",
    ),
    "current_ratio": (
        "Current ratio",
        "Current assets over current liabilities.",
        "Whether the company can pay what falls due within a year. Around 1.5-2 is comfortable in most industries.",
        "Very high is not automatically good: it can mean idle cash or inventory that is not selling.",
    ),
    "total_cash": (
        "Cash",
        "Cash and short-term investments on the balance sheet.",
        "The buffer: it decides how long a company can survive a bad year without asking anyone for money.",
        "It is a snapshot on one date, and the date is the quarter end — often the most flattering day of the quarter.",
    ),
    "total_debt": (
        "Total debt",
        "All interest-bearing debt, short and long term.",
        "Read it against cash and against operating cash flow, never on its own.",
        "Operating leases and off-balance-sheet commitments do not always show up here.",
    ),
    "fcf": (
        "Free cash flow",
        "Cash from operations minus capital expenditure.",
        "The money the business actually generates and can hand back. Harder to dress up than earnings.",
        "It swings with the investment cycle: a heavy capex year makes a healthy company look poor.",
    ),
    "fcf_yield": (
        "FCF yield",
        "Free cash flow over market cap. Computed, not downloaded.",
        "The cash return of the business as if it were a bond: directly comparable with an interest rate.",
        "It inherits the volatility of free cash flow. One year alone is a weak signal.",
    ),
    "operating_cashflow": (
        "Operating cash flow",
        "Cash generated by ordinary operations, before investment.",
        "Compare it with net income: if profits are consistently far above cash, ask why.",
        "Working capital movements can flatter or depress it without anything real changing.",
    ),
    "price": (
        "Price",
        "The last traded price of the session.",
        "It says nothing about value on its own: it only becomes information next to earnings, cash flow or book value.",
        "Comparing prices between companies is meaningless — a $5 stock is not cheaper than a $500 one.",
    ),
    "change_pct": (
        "Change %",
        "Percentage price change in the session.",
        "Noise, 95% of the time. It becomes information only alongside high relative volume.",
        "On illiquid stocks a single small trade produces -50% or +90%. Yahoo's unfiltered list is full of exactly these.",
    ),
    "change_abs": (
        "Change",
        "How many dollars the stock gained or lost in the session. Computed from price and percentage change, not downloaded.",
        "It is the 'Change' column of every screener. It only helps to read the percentage in absolute terms: $2 on $20 and $2 on $400 are different things.",
        "Comparing dollar changes across stocks with very different prices tells you nothing: the percentage is the only comparable figure.",
    ),
    "premarket_price": (
        "Pre-market price",
        "The last price traded before the opening bell (4:00 to 9:30 New York time).",
        "It shows how the market is reacting to what happened after yesterday's close: earnings, company news, morning macro data.",
        "It is a thin market: a few trades move the price, and the official open often erases half the move. It is not the price you will buy at.",
    ),
    "premarket_change_pct": (
        "Pre-market change",
        "How far the pre-market price sits from the previous close.",
        "The number you look at in the morning: which stocks are opening away from where they closed, and by how much.",
        "Without volume — which Yahoo does not publish for the pre-market — there is no way to tell whether the move is backed by real trading or by a handful of orders.",
    ),
    "week52_low": (
        "52W low",
        "The lowest price of the last twelve months.",
        "With the high it frames the range the stock has moved in: it tells you where today's price sits inside its own year.",
        "It is not a floor. A stock can sit on its 52-week low and still be expensive against its earnings.",
    ),
    "week52_high": (
        "52W high",
        "The highest price of the last twelve months.",
        "With the low it forms the year's range. A price pinned to the high signals a stock in trend — not one that is expensive or cheap.",
        "Ranking companies by distance from their high says nothing about their quality: it measures momentum, not the business.",
    ),
    "week52_position": (
        "Position in the 52W range",
        "Where today's price sits between the twelve-month low and high: 0% at the low, 100% at the high. Computed, not downloaded.",
        "It is the '52 Week Range' column of every screener, reduced to one number, so you can read the range without comparing three figures in your head.",
        "A wide range and a narrow one both produce 50%: always look at how far apart the low and the high actually are.",
    ),
    "week52_change": (
        "52W change",
        "Price return over the last twelve months.",
        "Momentum. Historically it has predictive power over 6-12 months, and it reverses sharply at turning points in the cycle.",
        "In a valuation engine it should carry little weight, or be kept separate: it is the only metric that measures the crowd rather than the company.",
    ),
    "beta": (
        "Beta (5Y)",
        "How much the stock moves relative to the market over five years.",
        "Above 1 it amplifies market moves, below 1 it dampens them.",
        "It is a historical correlation, not a promise: it changes when the business changes, and it says nothing about the risk of the company itself.",
    ),
    "score": (
        "Score",
        "Weighted average of the percentiles of the weighted metrics, on a 0-100 scale.",
        "It is a RANKING WITHIN THE UNIVERSE ANALYSED, not an absolute judgement: change the universe and every score changes without a single balance sheet moving.",
        "Read it together with data coverage: a high score built on half the metrics is worth less than a lower one built on all of them.",
    ),
    "coverage": (
        "Data coverage",
        "The share of the weights that actually found a value on this row.",
        "It is the score's confidence. Below the configured threshold the row is flagged unreliable and pushed to the bottom.",
        "Missing data is never counted as zero: it redistributes its weight. Treating gaps as zeros builds a ranking that rewards the companies that disclose the least.",
    ),
}
