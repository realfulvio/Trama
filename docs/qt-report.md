# Report di analisi riproducibili (Qt)

**File → Esporta report di analisi…** (inglese: File → Export analysis report…) crea un file ZIP che chi non ha Trama può aprire e leggere senza rete: tabelle CSV, grafici e layout SVG, le impostazioni statistiche di ogni risultato e una pagina `index.html` che li riassume.

## Cosa si può mettere nel report

Il dialogo elenca, per il progetto della scheda attiva, nell'ordine del navigatore:

- le tabelle di risultati di ogni analisi confermata (una riga per tabella);
- i grafici delle analisi;
- i layout.

Una riga che non si può esportare resta nell'elenco, in corsivo con un triangolo, non si può spuntare e dice il motivo:

| Motivo | Significa |
| --- | --- |
| Non calcolato | Il risultato non è ancora stato calcolato (progetto appena aperto). Aprire il foglio lo calcola nel modo normale; il report non calcola mai. |
| Non aggiornato o in errore | L'ultimo ricalcolo è in corso o non è riuscito: il report non usa un risultato che non corrisponde più ai dati. |
| Grafico importato | Grafici e layout importati da altri programmi non hanno un export SVG verificato. |
| Pannelli del layout non pronti | Almeno un pannello è in uno dei casi sopra. |

Fogli dati, fogli Info, cronologia e percorsi dei file di origine non entrano mai nel report, a meno di includere la copia del progetto.

## Il dialogo

- **Titolo** e **Nota**: riportati alla lettera nella pagina (caratteri come `$ < > &` restano testo).
- **Lingua del report**: inglese o italiano per i testi della pagina; parte dalla lingua dell'interfaccia.
- **Sezioni**: spunta per includere, **Sposta su / Sposta giù** per l'ordine, **Rinomina** (oppure F2 o doppio clic) per il nome nel report. Rinominare non cambia il progetto. **Seleziona tutto / Deseleziona tutto**.
- **Includi una copia del progetto (.alab)**: parte spenta. La copia è il progetto completo, con i dati originali, i fogli Info e i riferimenti interni.
- In basso, l'elenco finale dei file del report. Una selezione vuota, un titolo vuoto o un nome di sezione vuoto sono segnalati lì e **Esporta…** non procede.

Dopo **Esporta…** si sceglie il file `.zip`. Se esiste già, Trama chiede se sostituirlo; rispondendo No non scrive nulla.

Prima di scrivere, Trama fotografa i risultati scelti in un solo passaggio (con una barra e **Annulla**). Se uno dei risultati è cambiato tra il dialogo e la conferma, l'esportazione si ferma e chiede di riaprire il report. Una bozza di stile non confermata nell'Inspector va prima applicata o scartata, come per gli altri export. La scrittura dello ZIP gira in background: **Annulla calcolo** la ferma e il file precedente resta com'era. Alla fine la barra di stato mostra il percorso e il numero di sezioni.

Esportare non segna il progetto come modificato, non cambia il foglio selezionato e non conferma uno stile.

## Struttura del file

```
index.html          pagina UTF-8 senza script, collegamenti esterni o font remoti
manifest.json       descrizione verificabile del report
tables/001.csv      una voce per sezione, numerata nell'ordine scelto (da 1)
figures/002.svg
project.alab        solo con la copia del progetto
```

I nomi `tables/NNN.csv` e `figures/NNN.svg` dipendono solo dalla posizione: due sezioni con lo stesso titolo non si scontrano. Le tabelle sono il CSV di **File → Esporta** (UTF-8 con BOM, numeri con il punto, testo che sembra una formula preceduto da `'`). La pagina mostra le prime 25 righe di ogni tabella e collega il CSV completo; grafici e layout sono SVG vettoriali (testo come testo) collegati come immagini locali.

`manifest.json` (formato `trama-analysis-report`, `schema_version` 1):

- `project_title`, `metadata` (`trama_version`, `created_utc` in UTC, `language`): nessun percorso, nome del computer o credenziale.
- `sections`: per ognuna `label`, `kind` (`table` o `figure`), `method` (il codice canonico dell'analisi; per un layout il valore fisso `Layout`), `options` (la ricetta dell'analisi senza percorsi di file, copie in cache o disegni importati; per un layout colonne, carta, sfondo e pannelli) e `file`.
- `files`: ogni file del report tranne il manifest, ordinato per percorso, con dimensione e SHA-256 dei byte non compressi.

Con gli stessi risultati e la stessa ora, due report hanno file identici byte per byte: le voci dello ZIP hanno data fissa 1980-01-01, stessi permessi e stesso ordine, e l'ora del report è solo quella di `created_utc`.

## Verificare un report

```python
from analisi.report_bundle import verify_bundle
manifest = verify_bundle("report.zip")  # ValueError se qualcosa non torna
```

Il controllo legge lo ZIP senza estrarlo e rifiuta file modificati (checksum), file mancanti o in più, nomi duplicati o fuori dalla cartella, schema sconosciuto e dimensioni oltre il limite (100 sezioni, 256 MiB non compressi).
