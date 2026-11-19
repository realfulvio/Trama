# ANOVA multifattoriale completa in Qt (0.95 beta)

Dalla 0.95 l'interfaccia Qt espone gli stessi editor della finestra classica per **Analizza → Confronto tra gruppi → ANOVA multifattoriale**: la scelta dei termini del modello e l'ordine dei fattori per le somme dei quadrati di tipo I. Il motore (`analisi/anova_terms.py`, `analisi/anova_ss.py`) e le ricette non cambiano.

## Dove sta il codice

| File | Ruolo |
| --- | --- |
| `trama_qt/anova_model.py` | `TermEditor` (campo `Model terms`), `FactorOrder` (nota del tipo, ordine Su/Giù, anteprima dell'ordine dei termini), `AnovaFields` (collegamenti, ricetta canonica, controlli economici, messaggi tradotti) |
| `trama_qt/analysis_dialog.py` | Innesti piccoli: ramo `TERM_LIST` (accanto a `EQUATION_TEXT`, lontano dal ramo `ParameterTable`), `attach` a fine `configure_fields`, campi nascosti esclusi da `options()`, controlli prima della conferma |
| `trama_qt/strings.py` | Quattro testi solo Qt (`qt.anova.*`) in inglese e italiano; il resto viene da `analisi/i18n.py` (`anova.terms.*`, `anova.ss.*`) |
| `trama_qt/smoke.py` | Lo smoke da desktop guida anche l'ANOVA con gli editor veri |
| `tests/test_qt_anova.py` | 14 test offscreen (dialogo, finestra, oracolo indipendente) |

## Comportamento

**Variabili** tiene Risposta e Fattori. **Opzioni** mostra, nell'ordine:

1. *Selezione dei termini*: Gerarchia completa (predefinita) o Termini scelti.
2. *Ordine delle interazioni*: visibile solo con Gerarchia completa. Con Termini scelti è nascosto e resta fuori dalla ricetta, salvo che la ricetta aperta lo avesse già (il motore lo ignora; il valore torna utile se si rientra in Gerarchia completa).
3. *Somme dei quadrati*: Tipo III (predefinito, anche per le ricette senza la chiave), Tipo I, Tipo II. Sotto compare la nota del tipo: il ruolo dell'ordine per il Tipo I, la marginalità per il Tipo II quando il modello ha un'interazione.
4. Solo per il Tipo I: *Ordine dei fattori*, la lista dei fattori spuntati con **Su**/**Giù** (anche **Ctrl+Su**/**Ctrl+Giù** sulla lista) e la riga *I termini entrano in quest'ordine: …*. L'ordine diventa `Factors` della ricetta anche se differisce dall'ordine delle colonne. Un fattore tolto e rimesso riprende il suo posto; uno spuntato per la prima volta va in fondo. Cambiare tipo non perde l'ordine.
5. *Termini del modello*: con Gerarchia completa mostra il riepilogo del modello e la nota; con Termini scelti mostra **Seleziona tutto**, **Deseleziona**, **Aggiungi i termini richiesti** e tre gruppi di caselle: effetti principali, interazioni a due fattori, interazioni a tre fattori (limiti del motore: 8 fattori, ordine 3; oltre 8 fattori il riquadro lo dice e non mostra caselle).

Regole del draft:

- Un editor mai toccato segue la Gerarchia completa dei Fattori e dell'Ordine delle interazioni, quindi passando a Termini scelti si parte dal modello completo e si toglie. Il primo clic lo fissa. Passare a Gerarchia completa e tornare indietro conserva il draft.
- Un'interazione senza i suoi termini di ordine inferiore mostra *X richiede Y* in evidenza e abilita **Aggiungi i termini richiesti**. La conferma con gerarchia incompleta resta nel dialogo: banner con il messaggio del motore tradotto, scheda Opzioni, focus su **Aggiungi i termini richiesti**.
- Se si toglie un fattore, i termini che lo usano restano nel draft e vengono elencati (*Fuori dal modello finché i loro fattori non sono spuntati*). Rispuntando il fattore tornano. **Rimuovi i termini non disponibili** li elimina in modo esplicito. La conferma con termini non disponibili dà l'errore del motore su Termini del modello con il focus su quel pulsante: nulla sparisce in silenzio.
- Un termine orfano di una ricetta salvata (un fattore che non è più nell'elenco) è segnalato come *Dall'analisi salvata, non disponibili: … X non è nell'elenco dei Fattori* e si toglie con lo stesso pulsante.
- I nomi sono letterali: `Treatment $` e `Visit : phase` compaiono come nelle etichette dei risultati del motore (`"Visit : phase":Treatment $`). Una `&` nel nome resta visibile e non diventa una scorciatoia.

Ricetta scritta (come il dialogo classico): `Factors` nell'ordine scelto; `Model terms` come lista di liste di nomi, in ordine di modello; con Gerarchia completa niente `Model terms` e niente `Term selection` se la ricetta aperta non l'aveva; `Sums of squares` omesso quando è Tipo III e la ricetta non l'aveva. Il dialogo lavora su copie: **Annulla** lascia ricetta e risultati confermati.

Prima di chiudere il dialogo girano i controlli economici del motore (`anova_ss.sums_of_squares`, `anova_terms.check_options`, `check_comparison_controls`, alfa delle dimensioni dell'effetto, opzioni e budget della diagnostica). Il fit resta sul worker Qt; un errore del fit (per esempio *Il modello scelto non è identificabile*) riapre il dialogo con il messaggio tradotto e il focus sul campo, con il percorso Qt già in uso.

## Ripetere dalla GUI (dati sintetici)

Tabella (anche in `/mnt/project-files/qt-anova-095/` come `unbalanced.csv`):

```
Response,Treatment $,Visit : phase
9,Control,Start
11,Control,Start
13,Control,End
15,Control,End
15,Drug,Start
17,Drug,Start
23,Drug,End
25,Drug,End
12,Control,Start
22,Drug,End
26,Drug,End
```

1. File → Apri il CSV. Analizza → Confronto tra gruppi → ANOVA multifattoriale. Variabili: Risposta `Response`, Fattori `Treatment $` e `Visit : phase`.
2. Opzioni: Termini scelti. Spunta solo l'interazione e togli i due effetti principali. Esegui: il dialogo resta aperto, il banner dice che l'interazione richiede `Treatment $, "Visit : phase"` e il focus è su **Aggiungi i termini richiesti**. Premi Spazio, poi Esegui. Il foglio *Model terms* elenca i tre termini.
3. Cambia parametri…: Somme dei quadrati Tipo I, seleziona `Treatment $` e premi Giù (o Ctrl+Giù). L'anteprima diventa `"Visit : phase" → Treatment $ → "Visit : phase":Treatment $`. Annulla: la ricetta e i risultati restano quelli confermati. Rifai e conferma: SS di tipo I con `Visit : phase` per primo 168,776 e `Treatment $` 153,712; RSS 18,667 come prima.
4. Tipo II: le SS per effetto sono le stesse nei due ordini.
5. Modifica una cella e escludine un'altra: il risultato si ricalcola. Salva il progetto, riaprilo: ordine dei fattori e nomi dei termini restano. Esporta la tabella in CSV: le etichette dei termini sono le stesse.
6. Ripeti in inglese (scheda Visualizza → Lingua…, vale dal riavvio): stessa ricetta.

Con la tabella bilanciata (le prime 8 righe): Gerarchia completa ordine 2 dà F 64, 36 e 4; con i soli effetti principali F 40 e 22,5 e il foglio *Model terms*.

## Prove

- Verificatore del pacchetto: base `7a7340c` oracolo e dispatcher PASS, contratto Qt FAIL (Model terms `kept`, ordine perso); testa PASS su tutti e tre.
- `python -m unittest tests.test_anova_terms tests.test_anova_ss tests.test_qt_shell tests.test_qt_anova`.
- `python -m trama_qt --smoke CARTELLA` a 1024×768 e 1600×1000 (offscreen con schermo emulato nel container), EN e IT: screenshot `*-anova-*.png`.
- **Windows NON PROVATO.** Nessuna prova nativa né DPI reale in questa consegna.
