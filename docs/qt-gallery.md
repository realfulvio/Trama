# Galleria dei grafici (Qt)

La Galleria mostra tutti i grafici e i layout del progetto come schede con anteprima, per trovarne uno e aprirlo senza scorrere il navigatore.

## Dove si trova

**Visualizza → Galleria** (inglese: View → Gallery), oppure **Ctrl+Maiusc+G**. Prende il posto del foglio aperto; **Esc**, **Alt+Sinistra** o il pulsante **Torna al foglio** riportano al foglio da cui si era partiti, con il focus dove era.

## Cosa si vede

Ogni scheda ha un'anteprima, il nome, il tipo e lo stato. Lo stato è scritto a parole oltre che con icona e colore:

| Stato | Significa |
| --- | --- |
| Pronto | Il risultato è calcolato e aggiornato. L'anteprima mostra il grafico (per un layout, la pagina con tutti i pannelli, nelle sue proporzioni). |
| Non calcolato | Il foglio non ha ancora un risultato (progetto appena aperto da file). Al posto dell'anteprima c'è un segnaposto. |
| Obsoleto | C'è un risultato, ma l'ultimo ricalcolo non è riuscito o è in corso. L'anteprima mostra l'ultimo risultato confermato, con una fascia "Obsoleto". |
| Calcolo non riuscito | Non c'è un risultato e l'ultimo calcolo ha dato errore. Aprire il foglio mostra il motivo. |

Un layout prende lo stato peggiore dei suoi pannelli. Nomi uguali sono numerati ("Grafico 2/3 con questo nome").

Le schede Tutti / Grafici / Layout in alto filtrano per tipo e mostrano il conteggio. Si parte da Tutti.

## Cerca

La casella **Cerca per nome** (Ctrl+F) filtra mentre si scrive. La ricerca ignora maiuscole, accenti e spazi doppi e cerca la frase intera così com'è: `Calibrazione $` trova un nome con quel testo, il `$` non è un carattere speciale. Non cambia mai i dati. **Freccia giù** passa dalla casella alla lista, **Invio** nella casella apre il primo foglio che corrisponde.

I filtri e la galleria aperta sono uno stato della vista: non si salvano nel progetto e non lo segnano come modificato. Restano per la sessione e si azzerano quando si apre o si crea un altro progetto.

## Aprire un foglio

**Invio** sulla scheda scelta con le frecce o il doppio clic aprono il foglio con la navigazione normale. Se il foglio non ha un risultato viene calcolato come sempre (avanzamento, errori nel messaggio, Annulla). La galleria da sola non calcola mai niente: scorrere o cercare non avvia calcoli. I layout importati si aprono come layout.

## Anteprime

Si disegnano solo per le schede visibili, una figura alla volta, con una piccola coda; scorrendo si dimenticano quelle uscite dalla vista. Una cache limitata (64 schede) le conserva e le butta se cambiano dati, stile (Format Graph, Inspector) o risultato. Le anteprime non toccano le figure che i fogli mostrano e si fermano mentre un calcolo è in corso. Cambiando progetto, chiudendo la galleria o la finestra sparisce tutto.

Se un'anteprima non si può disegnare la scheda resta e dice che l'anteprima non è disponibile: il foglio si apre normalmente. L'esportazione (PNG, SVG, PDF, layout) non cambia e dà gli stessi byte di prima.

## Senza grafici o in caso di errore

Una pagina breve spiega cosa fare (creare un grafico con Ctrl+G e riaprire la galleria con Ctrl+Maiusc+G) e si usa solo con la tastiera: Esc torna al foglio. Lo stesso vale se la ricerca non trova niente o se l'elenco non si può costruire.

## Per chi sviluppa

- `trama_qt/gallery_catalog.py`: elenco, stati, numerazione, ricerca (senza Qt).
- `trama_qt/gallery_thumbs.py`: cache LRU e servizio di anteprime (solo thread della GUI, una figura per tick, `savefig` e mai un canvas nuovo).
- `trama_qt/gallery.py`: modello, delegato e pagina. Ganci per il verificatore: `window.actions["gallery"]`, lista `sheetGallery`, casella `gallerySearch`, `UserRole` = riferimento della navigazione (es. `("graph", 0)`).
- `trama_qt/window.py`: `toggle_gallery`, `open_gallery`, `close_gallery`, `_drop_gallery`; `refresh()` e `_replace_page` tengono la galleria coerente.
- Test: `tests/test_qt_gallery.py` (38 test); misura con 120 schede: `python tests/perf_qt_gallery.py --mode lazy|eager`; smoke: passi "gallery" di `python -m trama_qt --smoke`.
