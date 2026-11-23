# Ripeti analisi su altri fogli

Chi tiene un foglio dati per lotto o per esperimento conferma una ricetta una volta e poi la ripete sugli altri
fogli. **Analisi → Ripeti analisi su altri fogli…** (anche dal menu contestuale del navigatore) aggiunge a ogni foglio scelto una copia autonoma della ricetta, collegata alle colonne di quel foglio.
Il comando esiste sia nell'interfaccia Classica (Tk) sia in Classica Qt, con gli stessi testi, controlli e rifiuti:
la logica sta in `analisi/repeat_analysis.py` (motore), `analisi/repeat_analysis_assistant.py` (stato
dell'assistente) e `analisi/repeat_analysis_text.py` (testi IT/EN); le due finestre la disegnano soltanto.

## I tre passi

1. **Ricetta.** Si parte da un risultato o da un grafico. L'assistente mostra origine e metodo e chiede se ripetere
   solo l'analisi selezionata o anche i passaggi a valle compatibili (le analisi che leggono i suoi risultati). Il
   riepilogo dice quali risultati alimentano i passaggi successivi e, per quelli lasciati fuori, il motivo.
2. **Fogli e colonne.** Si scelgono uno o più fogli dati. Il foglio d'origine e le viste archiviate in sola lettura
   restano visibili ma non selezionabili, con il motivo. Per ogni foglio si sceglie la colonna da usare per ogni
   colonna della ricetta: sono proposti solo i nomi identici, un nome simile si usa solo se lo si sceglie a mano.
   Avanti resta disattivato finché manca una scelta, una colonna è scelta due volte, una colonna numerica contiene
   testo o le formule del foglio non si calcolano; il motivo è scritto sotto la tabella.
3. **Anteprima.** Per ogni destinazione: le colonne usate, le nuove analisi con il loro nome e, per i passaggi a
   valle, da quale nuova analisi leggono. Dati, formule, esclusioni, Info, risultati e grafici esistenti restano
   invariati.

**Ripeti** calcola tutte le copie sul worker, con avanzamento e **Annulla calcolo**. Il progetto cambia solo se
tutte le copie si calcolano e il progetto non è stato chiuso né modificato nel frattempo: è un'unica transazione.
Annullare, un errore o un progetto cambiato lasciano il progetto com'era. Se una copia non si calcola, il messaggio
nomina foglio, metodo e problema e lo stesso assistente si riapre con le scelte fatte.

## Cosa diventano le copie

Ogni copia è una normale analisi di Trama, nel foglio di destinazione, in coda alle sue analisi (gli slot esistenti
non cambiano). Ha una nuova identità persistente; i figli sono collegati al nuovo produttore dello stesso foglio,
quindi **Cambia risultato di ingresso…**, la famiglia e il navigatore li riconoscono. Ricalcolo, esclusioni,
modifica delle celle, salvataggio, riapertura ed esportazione funzionano come per le altre analisi; modificare le
opzioni di una copia non tocca l'originale.

I nomi seguono la convenzione di Trama: un'analisi senza nome mostra «Metodo of Tabella». La copia ha un nome
esplicito solo se l'originale lo aveva o se il nome sarebbe già usato nel foglio: allora si aggiunge « (2)», « (3)»…
Nomi di fogli, colonne e analisi sono testo letterale del progetto e non si traducono.

## Campi rimappati (registro `CONTRACTS`)

Solo i metodi con un contratto esplicito possono viaggiare. Il contratto elenca i campi delle opzioni che contengono
colonne della tabella analizzata; nient'altro viene rinominato, nemmeno un'opzione o un letterale che ha per caso lo
stesso testo di una colonna.

| Metodo | Campi rimappati | Tabelle prodotte |
|---|---|---|
| Transform | Variables (una o più, numeriche) | Transformed (passa le colonne) |
| Normalize | Variables (una o più, numeriche) | Normalized (passa le colonne) |
| Descriptive statistics | Variables (una o più, numeriche) | Summary |
| Linear regression | X, Y (numeriche) | Regression, Residuals, Curve coordinates, bande puntuali, Linear estimates |
| Nonlinear regression | X, Y columns (numeriche); Grouping variables (facoltative, qualsiasi valore); SD column (facoltativa, numerica) | Parameters, Fit, Residuals, Curve coordinates, Runs test, Replicate lack of fit, Band, Band status |

**Gruppi facoltativi.** Un campo facoltativo vuoto nella ricetta resta vuoto e non chiede colonne. Se la ricetta lo
usa, la colonna va scelta come le altre. Le tabelle per gruppo della regressione non lineare (per esempio
«Parameters: A») non fanno parte del contratto: un'analisi che le legge resta fuori, con il motivo.

**Analisi sui risultati.** Transformed e Normalized hanno una colonna per ogni variabile scelta, con lo stesso nome:
un'analisi che le legge segue la rimappatura del suo produttore (X → Tempo nel produttore diventa X → Tempo anche
nel figlio). Le altre tabelle hanno colonne fisse e il figlio mantiene le opzioni così come sono. Un passaggio a valle
resta fuori quando legge una tabella o una colonna che la copia non fornisce in ogni destinazione, o quando il suo
produttore non viene ripetuto.

**Ricette rifiutate.** Con il motivo: metodi senza contratto; analisi che leggono un altro foglio (unione di fogli),
un file importato o una vista importata; grafici che disegnano i confronti di un'altra analisi; analisi che leggono
il risultato di un'altra (si ripete l'analisi da cui partono, con i passaggi a valle); opzioni salvate non valide;
colonne non più presenti nel foglio d'origine.

## Proprietà di stile

Il formato del grafico della copia parte da quello dell'originale. Le serie che portano il nome di una colonna
rinominata seguono il nuovo nome; le forme disegnate e le annotazioni libere restano sul grafico originale. Se il
formato non si adatta alle serie della copia, la copia usa il formato predefinito e la barra di stato lo dice.
Layout e colori delle celle dei risultati restano del foglio originale.

## Limiti

Il limite di 256 analisi per foglio e di 65.536 analisi per progetto vale anche per le copie: un foglio che lo
supererebbe non è selezionabile.

## API

```python
from analisi.repeat_analysis import plan_repeat, stage_repeat

plan = plan_repeat(tables, ("Original", 0), {"Lot B": {"X": "Tempo", "Y": "Segnale"}}, follow=True)
staged = stage_repeat(tables, plan, cancel=lambda: False)
```

`plan_repeat` controlla ricetta e scelte e solleva `RepeatError` (una `ValueError`) con un codice traducibile;
`stage_repeat` restituisce una mappa completa dei fogli in cui ogni destinazione è un nuovo `Dataset` con le copie.
`cancel` è un predicato senza argomenti: annullare solleva `ChainCancelled`. Nessuna delle due funzioni modifica i
propri argomenti né apre finestre.
