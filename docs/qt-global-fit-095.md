# Global fit custom equation in Qt (0.95 beta)

Pacchetto `Trama-Claude-Qt-Fit-Globali-095`. Base `7a7340cf4f0900aa056a3f67fedf8afd28db292f` (main dopo la PR #56).
Il motore (`analisi/global_custom_fit.py`) non cambia: cambiano solo l'interfaccia Qt, i test e lo smoke.

## Cosa c'è

- **Coefficienti** (`Global coefficient list`), modulo `trama_qt/global_fit.py`, classe `GlobalCoefficientEditor`.
  Tabella Nome, Valore iniziale / fissato, Inferiore, Superiore, Ambito (Locale, Condiviso, Fisso con un menu a
  tendina nella cella). Scrive i campi canonici `name, start, lower, upper, fixed, shared`; il valore di un
  coefficiente Fisso resta in `start`, come fa il motore. Limiti vuoti diventano `None`, la virgola decimale è
  accettata, un numero non finito è un errore sul campo. Pulsanti Aggiungi, Rimuovi, **Leggi dall'equazione**.
- **Leggi dall'equazione** usa il tokenizzatore del compilatore (`analisi.custom_equations._tokens`) e poi
  `compile_equation`, in entrambe le sintassi (Aritmetica e Condizionale). L'elenco segue l'ordine di prima
  comparsa nell'equazione. I coefficienti ancora presenti conservano iniziale, limiti, valore fissato e ambito;
  quelli tolti sono elencati nella nota. Mentre si scrive l'equazione, la nota segnala i coefficienti non usati e
  i nomi dell'equazione che mancano nell'elenco. Un'equazione che non compila lascia l'elenco com'è e mostra
  l'errore tradotto.
- **Vincoli per serie** (`Global series constraints`), classe `GlobalSeriesEditor`. A sinistra le serie delle
  righe complete di X, Y e Group (`series_in` del motore, nomi letterali: `Control $`, `Batch B`); a destra una
  riga per coefficiente con quattro campi distinti: Iniziale, Inferiore, Superiore, Valore fisso. Un campo vuoto
  eredita: il valore comune è mostrato in grigio (`−∞`/`+∞` per i limiti assenti, "stimato" per un valore
  non fissato). Per un coefficiente Condiviso sono attivi solo i limiti, con la nota che valgono per tutte le
  serie (l'intervallo comune è l'intersezione, come in `_bind`); per un Fisso sono attivi solo i limiti. La
  ricetta resta `[{series, parameters: {A: {fixed: 1.0}}}]`; una chiave assente eredita.
- Quando cambiano X, Y, Group, Pesatura o colonna SD le serie si ricalcolano. Le serie con vincoli che non
  compaiono più restano nell'elenco marcate "fuori dai dati", e i vincoli di coefficienti tolti sono elencati.
  **Rimuovi vincoli non applicabili** li elimina in modo esplicito. Una conferma con un vincolo non applicabile
  seleziona la serie e porta il cursore sul suo campo.
- Il calcolo delle serie usa un'equazione segnaposto: un'equazione o un elenco di coefficienti scritti a metà
  non svuotano l'elenco delle serie.

## Dialogo (`trama_qt/analysis_dialog.py`)

Innesti piccoli, tutti delegati a `trama_qt/global_fit.py`:

1. Pagine Variabili, Equazione, Coefficienti, Vincoli di serie, Bande e previsioni, Opzioni (come il dialogo
   classico). Pesatura e Colonna SD stanno in Variabili.
2. Ramo `elif kind in (global_fit.PARAMETER_LIST, global_fit.SERIES_LIST)` subito dopo il ramo `ParameterTable`,
   in costruzione e in `options()`. I due tipi di controllo sono distinti (`Global coefficient list` e
   `Global series constraints`), quindi `dialog.controls` non li tiene più come `kept`.
3. `focus_field(name, error=None)`: dopo aver aperto la scheda giusta, un editor composto con `focus_problem`
   porta il cursore sulla cella dell'errore (localizzata dall'editor o letta dalla frase del motore).
4. `accept()` chiama `global_fit.confirm`: toglie le chiavi nuove che valgono come il default del motore (così
   una ricetta salvata e confermata senza modifiche torna identica) e poi `check_options(frame, options)`. Un
   `FieldError` resta nel dialogo con messaggio tradotto e focus; il fit gira una volta sul worker Qt.
5. Messaggi del banner tradotti con le frasi `gfit.error.*` già nel catalogo.

Copie: gli editor leggono i valori del chiamante e lavorano su testo proprio. Esegui (la conferma del dialogo)
trasferisce i valori nella ricetta; Annulla non tocca la ricetta del chiamante. Le due riaperture consecutive
partono dall'ultima ricetta confermata (test `test_cancel_leaves_the_caller_values_...`).

### Sovrapposizioni con il pacchetto ANOVA (stesso file)

Il pacchetto ANOVA-095 tocca gli stessi punti di `analysis_dialog.py`; i conflitti attesi sono di righe vicine,
non di logica:

- import: `from . import global_fit` sopra `from .labels import ...`;
- costruzione dei widget e `options()`: il ramo globale sta subito dopo `ParameterTable`, il ramo `TERM_LIST`
  dell'ANOVA andrà accanto, separato;
- `accept()`: qui `options = global_fit.confirm(self, self.options())`; i validatori ANOVA vanno sulla stessa
  riga o subito dopo;
- `focus_field` (qui firma `focus_field(name, error=None)` e `focus_problem`): se l'ANOVA porta il focus sul
  selettore dei termini può riusare lo stesso aggancio;
- `configure_fields`: qui le pagine sono un dizionario per chiave e la scheda Opzioni vuota si toglie per
  oggetto, non per indice 1;
- `trama_qt/smoke.py`: una riga dopo `self.editors(window, refs)`.

## Prove

| Prova | Esito |
| --- | --- |
| `verify.py --repo … --qt` sulla base 7a7340c | oracle PASS, dispatcher PASS, **Qt editor FAIL** (Parameters e Series constraints senza editor, EN e IT) |
| `verify.py --repo … --qt` sulla testa | oracle PASS, dispatcher PASS, **Qt editor PASS** |
| `TRAMA_REPO=… python -m unittest discover -s tests` del pacchetto | OK |
| `tests.test_qt_global_fit` (nuovo, offscreen) | 14/14 OK |
| `tests.test_global_custom_fit`, `test_global_custom_profiles`, `test_global_response_bands`, `test_global_response_queries`, `test_global_uncertainty_contract`, `test_qt_shell`, `test_qt_global_fit` | 121 OK |
| `python -m trama_qt --smoke`, Xvfb 1024×768, EN e IT | PASS, 98 screenshot |
| `python -m trama_qt --smoke`, Xvfb 1600×1000, EN e IT | PASS, 98 screenshot |
| Suite completa (263 file, uno per volta, Xvfb 1920×1080, py3.12 + Tk 8.6, Qt offscreen) | 3514 test; unico rosso `test_formula_windows` (1 failure + 1 error), identico sulla base 7a7340c (pandas 3.1, non introdotto qui) |

Accettazione del pacchetto, punto per punto (test in `tests/test_qt_global_fit.py`):

1. A locale e B condiviso su `A+B*X`: A = 1 e 4, B = 2, RSS 0,5, df 5. Con A fissato a 1 per `Control $`
   (dall'editor) stesse stime, df 6, riga Fixed.
2. Limiti validi accettati; inferiore oltre superiore → errore su Coefficienti, cella Inferiore di B, valori
   conservati; valore fisso su un condiviso → errore su Vincoli di serie, campo Valore fisso di B in `Control $`;
   vincolo su una serie tolta (Group → SD) → errore, campo del vincolo; vincolo su un coefficiente tolto → errore,
   campo del vincolo. Dopo la correzione la conferma passa.
3. `demo.alab` in IT e EN: ricetta identica alla canonica, Annulla prima di confermare (ricetta e risultati
   invariati), conferma senza modifiche (ricetta identica), modifica di una cella (`10,75`) e esclusione di una
   cella con ricalcolo (df 5), salvataggio, riapertura, export della tabella Parameters in CSV e del grafico in SVG.
4. Equazione aritmetica e condizionale `if(X < T, A + B*X, A + B*T)`: la soglia T stimata è rifiutata su
   Coefficienti con il focus sull'Ambito di T; con T fisso il risultato coincide con `analyse` sulla stessa
   ricetta. Le suite globali esistenti (profili, bande della risposta, previsioni) passano.
5. Smoke a 1024×768 e 1600×1000, IT e EN: editor veri, errore con focus sulla cella, correzione, Annulla,
   calcolo sul worker, salvataggio, riapertura e ricalcolo, screenshot `*-global-*.png`. Pulsanti e campi con
   errore raggiungibili da tastiera (Tab/frecce nella tabella, F2 o digitazione per modificare, menu Ambito).

**Windows NON PROVATO.** Lo smoke gira su Linux/Xvfb (piattaforma xcb, DPI logico 96, rapporto 1.0): non è
un risultato Windows né un DPI nativo. Il collaudo Windows a 100% e 150% resta a Codex.

## Ripetere dalla GUI

1. File → Apri `tests/data/qt_global_fit/linear.csv` (o `demo.alab`).
2. Analizza → Regressione e curve → Adattamento globale di un'equazione personalizzata. X = X, Y = Y,
   Gruppo = Series.
3. Equazione: `A+B*X`. Coefficienti: Leggi dall'equazione; A Locale, B Condiviso con Inferiore 0 e Superiore 4.
4. Vincoli di serie: `Control $`, riga A, Valore fisso `1`.
5. Prova un errore: B Inferiore 3, Superiore 1, Esegui → banner rosso, cursore sulla cella; correggi.
6. Esegui → foglio Parameters: A di `Control $` Fixed 1, A di `Batch B` 4, B 2; Global fit: df 6, RSS 0,5.
7. Cambia parametri…, cambia qualcosa, Annulla: la ricetta resta quella confermata.
8. Gruppo → SD: `Control $` diventa "fuori dai dati"; Rimuovi vincoli non applicabili.
9. Salva, riapri, Ricalcola; Esporta tabella / Esporta grafico.

Evidenze (fuori dal sorgente): `/mnt/project-files/qt-global-fit-095/` del progetto (rapporti del verificatore,
log, screenshot dello smoke).
