# Esportare più figure (Qt)

**File → Esporta più figure…** scrive un file per ogni grafico o layout scelto del progetto attivo, in PNG, SVG o PDF, dentro una cartella. È diverso da **Esporta più fogli in PDF**, che continua a produrre un unico PDF multipagina.

## Esempio

1. Apri `sessione.alab` (due tabelle, Calibrazione $ A e Calibrazione B, ciascuna con un grafico XY).
2. Apri i due grafici: Trama li calcola alla prima apertura. Crea un layout con i due pannelli (Grafico → Nuovo layout).
3. File → Esporta più figure…: l'elenco mostra, nell'ordine del navigatore,
   `Grafico · XY series of Calibrazione $ A`, `Grafico · XY series of Calibrazione B`, `Layout · Figura 1`.
4. Scegli PDF, larghezza 120 mm e la cartella. La colonna «Nome del file» mostra già i nomi:
   `XY series of Calibrazione $ A.pdf`, `XY series of Calibrazione B.pdf`, `Figura 1.pdf`, ognuno con la sua dimensione finale.
5. Esporta: la barra avanza figura per figura e alla fine il riepilogo dice per ogni file *Esportato*, *Saltato*, *Errore* o *Annullato*.

Ogni PDF ha una sola pagina. Il layout resta vettoriale in SVG e PDF (stessa via di Esporta con opzioni: `Project.export_layout`); i grafici passano da `analisi.figure_export.export_figure`.

## Cosa si può esportare

- Grafici nativi e layout nativi già calcolati. Le figure senza risultato, con un errore di calcolo o i layout con pannelli da ricalcolare compaiono disattivati con il motivo accanto. Ricalcolarli è un'azione esplicita nell'app: il dialogo non lancia calcoli.
- Grafici e layout importati compaiono disattivati: conservano la loro esportazione originale.
- Due fogli con lo stesso titolo hanno righe distinte (`… (2)`) e file distinti. I titoli nel progetto non cambiano.

## Opzioni

Le stesse di Esporta con opzioni e con gli stessi controlli: larghezza in mm (vuota = ogni figura alla sua dimensione), DPI per il PNG, testo SVG come testo o tracciati, sfondo trasparente. Il dialogo parte dalle scelte della sessione di Esporta con opzioni e non le modifica. Un valore non valido, o una figura che con quella larghezza supererebbe i limiti, disattiva Esporta e il messaggio dice quale figura.

Prima di aprire il dialogo Trama sistema la bozza dell'Inspector (Applica, Scarta o Annulla). Annulla lì, oppure nel selettore della cartella, chiude senza creare file. Il progetto, la selezione, lo stato salvato e la cronologia di modifica restano gli stessi dopo l'export e dopo l'annullamento.

## Nomi dei file

Contratto: `trama_qt.batch_export.plan_filenames(titles, format, occupied=()) -> list[str]`, con `format` uguale a `png`, `svg` o `pdf` (altri valori: `ValueError`).

- Una sequenza di caratteri di controllo o vietati da Windows (`< > : " / \ | ? *`) diventa un solo `_`: `Assay: A/B` → `Assay_ A_B`.
- Spazi e punti ai bordi vengono tolti; Unicode resta (`R²`, `… Δ`, spazi e punti Unicode all'interno restano letterali). Il nome è normalizzato NFC e lo stem ha al massimo 96 caratteri. Uno stem vuoto diventa `Figure`.
- I nomi di dispositivo Windows ricevono `_` davanti, anche prima di una seconda estensione: `CON` → `_CON`, `LPT9.tmp` → `_LPT9.tmp.pdf`.
- Il confronto ignora maiuscole e forma Unicode (NFC), sia tra i nuovi nomi sia con quello che c'è già nella cartella, cartelle comprese. Chi collide riceve ` (2)`, ` (3)`… prima dell'estensione.

## Scrittura sicura

- I file vanno solo nella cartella scelta: i nomi non contengono separatori e non iniziano con un punto.
- Ogni figura viene scritta dall'esportatore esistente in una cartella temporanea privata (`.trama-export-…`) dentro la destinazione, poi riletta da un lettore indipendente (Pillow per il PNG, XML per l'SVG, PDFium per il PDF: una pagina).
- Il file verificato viene pubblicato con un collegamento che non sostituisce mai un nome esistente (`os.link`); dove i collegamenti non ci sono, con una creazione esclusiva (`open(..., "xb")`) e la copia. Se la copia fallisce viene tolto solo il file parziale creato da questa esportazione. La cartella temporanea viene sempre rimossa.

### Conflitti

Subito prima di pubblicare, Trama rilegge la cartella. Se nel frattempo qualcuno ha creato un file (o una cartella) con lo stesso nome, anche con maiuscole diverse, quella figura risulta **Saltata: nella cartella è comparso un file con questo nome; nessun file è stato sostituito**. Le altre figure proseguono. Rifacendo l'export i nomi nuovi ricevono il suffisso.

### Errori

- L'errore di una figura (renderer, file non valido) la segna come **Errore** con il messaggio; le altre proseguono se la cartella è ancora scrivibile.
- Se la cartella non esiste, non è scrivibile o sparisce durante il lotto, l'export si ferma: le figure rimaste risultano **Saltate: la cartella non è scrivibile**.

### Annullamento

Annulla (o Esc) mentre il lotto è in corso ferma l'export dopo il file in corso: quelle in attesa risultano **Annullate**, i file già scritti restano validi nella cartella. La finestra resta aperta con il riepilogo finché non premi Chiudi.

## Concorrenza

Le figure appartengono ai canvas Qt, quindi non passano mai a un altro thread. Il dialogo scrive una figura per giro del ciclo eventi Qt (`QTimer.singleShot`), sul thread dell'interfaccia: tra un file e l'altro l'interfaccia si aggiorna e Annulla risponde. Il dialogo è modale e il comando parte solo se non c'è un calcolo in corso, quindi progetto, schede e figure non cambiano durante il lotto. Il progetto è quello della scheda attiva al momento del comando.

## Prove

- `python -m unittest tests.test_qt_batch_export` (motore e finestra, offscreen).
- `python -m trama_qt.batch_export_smoke CARTELLA [--fixture sessione.alab]`: EN/IT, chiaro/scuro, PNG/SVG/PDF due volte, screenshot del dialogo e del riepilogo, `results.json` con le dimensioni misurate, `status.txt`.
- `python -m trama_qt --smoke CARTELLA` apre anche questo dialogo sul progetto dello smoke e controlla che entri nello schermo senza testi tagliati.
