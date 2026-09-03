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

- **Chiusura di ieri** e **Pre-mercato**, due sezioni con gli stessi strumenti.
- **La seduta è dichiarata in testata** — un aggiornamento fatto la mattina in
  Italia pubblica la chiusura del giorno prima a New York, e la data del file
  direbbe un'altra cosa.
- **I dati mancanti non valgono zero**: redistribuiscono il loro peso e
  abbassano la *copertura*, pubblicata accanto al punteggio. Trattare i buchi
  come zeri costruisce classifiche che premiano chi pubblica meno dati.
- Ogni metrica ha la sua scheda *Cos'è / Come si legge / Attenzione*.
- Italiano e inglese.

## Cos'è questa copia

Una **fotografia**: i dati sono incorporati nell'HTML, quindi la pagina si apre
ovunque e anche senza rete, ma non si aggiorna da sola e non ha i comandi. Il
motore che scarica i prezzi e ricalcola i punteggi gira sul computer.

## Avvertenze

Il punteggio è un **ordinamento relativo all'universo analizzato**, calcolato su
dati storici di terzi che possono essere errati o incompleti. Cambiando universo
cambiano tutti i punteggi senza che nessun bilancio sia cambiato. **Non è una
raccomandazione di investimento e non sono un consulente finanziario.**

Dati di mercato via Yahoo Finance (API non ufficiali).
