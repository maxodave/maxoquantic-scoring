# Maxoquantic Scoring

Una pagina sola, senza dipendenze: i 150 titoli USA più scambiati **per denaro**
(prezzo × volume) con un punteggio fondamentale, la loro copertura dati e i
filtri dichiarati.

👉 **[Apri la pagina](https://maxodave.github.io/maxoquantic-scoring/)**

## Perché "per denaro" e non per volume

La pagina *Most Actives* di Yahoo Finance ordina per **numero di azioni**
scambiate. Non è la stessa cosa dell'attività: in una seduta recente NVIDIA ha
mosso 35,2 miliardi di dollari e PG&E 1,6, ma con 156 milioni di azioni contro
119 la distanza in classifica quasi spariva — e nella seduta precedente PG&E
stava davanti pur muovendo dodici volte meno denaro. Quella lista si regge poi
su **tre filtri applicati senza dichiararli**; toglierli la riempie di penny
stock. Qui i filtri sono scritti sopra la tabella, uno per uno, con il contatore
e la ✕ per rimuoverli.

## Cosa c'è dentro

- **Chiusura** e **Pre-mercato**, due sezioni con gli stessi strumenti. A borsa
  aperta la prima si muove insieme alla seduta, e cambia nome per non chiamare
  «chiusura» dei prezzi che stanno ancora correndo: il pallino rosso sta sulla
  sezione viva.
- **La seduta è dichiarata in testata** — un aggiornamento fatto la mattina in
  Italia pubblica la chiusura del giorno prima a New York, e la data del file
  direbbe un'altra cosa.
- **I dati mancanti non valgono zero**: redistribuiscono il loro peso e
  abbassano la *copertura*, pubblicata accanto al punteggio. Trattare i buchi
  come zeri costruisce classifiche che premiano chi pubblica meno dati.
- Ogni metrica ha la sua scheda *Cos'è / Come si legge / Attenzione*.
- Italiano e inglese.

## Come si aggiorna

Da sola, qui su GitHub: non c'è niente da tenere acceso su nessun computer.

Un'azione programmata gira **otto volte al giorno nei giorni di borsa** e
scarica solo ciò che a quell'ora esiste, poi ricostruisce `index.html` con i
dati dentro e lo pubblica.

| fascia | corse | cosa scarica |
|---|---|---|
| prima dell'apertura | 2 | il pre-mercato |
| a borsa aperta | 4 | i prezzi della seduta, mentre si muovono |
| dopo la chiusura | 2 | i prezzi di chiusura, la seconda a chiusura consolidata |

Gli orari sono scritti in UTC, che non segue l'ora legale: sono scelti perché
restino nella fascia giusta sia d'estate sia d'inverno.

Tre accorgimenti perché non saturi niente:

| | |
|---|---|
| **La cache viaggia fra una corsa e l'altra** | Universo (330 quote) e fondamentali (150 schede) valgono 7 giorni: una corsa normale fa ~150 richieste invece di ~500, e quella lunga capita una volta a settimana |
| **Lo stato è la pagina stessa** | `index.html` contiene entrambi gli insiemi di dati; prima di aggiornare vengono riletti da lì. Una corsa di solo pre-mercato non fa sparire la chiusura, e se la cache viene sfrattata non si perde niente |
| **Si pubblica solo se è cambiato qualcosa** | La pagina viene costruita in modo deterministico: dati identici, file identico, nessun commit e nessuna ricostruzione del sito |

Si può anche lanciare a mano da **Actions → Aggiorna i dati → Run workflow**,
scegliendo cosa aggiornare.

## Cos'è questa copia

I dati sono incorporati nell'HTML: la pagina si apre ovunque e continua a
funzionare anche senza rete una volta caricata. Non ha i comandi del motore,
perché non c'è nessun motore dietro un sito — c'è l'azione programmata.

## Avvertenze

Il punteggio è un **ordinamento relativo all'universo analizzato**, calcolato su
dati storici di terzi che possono essere errati o incompleti. Cambiando universo
cambiano tutti i punteggi senza che nessun bilancio sia cambiato. **Non è una
raccomandazione di investimento e non sono un consulente finanziario.**

Dati di mercato via Yahoo Finance (API non ufficiali).
