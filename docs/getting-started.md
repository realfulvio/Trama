# Iniziare con Trama

[Presentazione](../README.md) · [Funzionalità](features.md)

## Aprire la versione Windows

1. Apri la pagina [Download](https://github.com/realfulvio/Trama/releases).
2. Scarica `Trama-<versione>-Windows-x64.zip` (nelle release precedenti `TramaStat-<versione>-Windows-x64.zip`), non l'archivio del codice sorgente.
3. Estrai **tutta** la cartella in una posizione in cui puoi leggere e scrivere.
4. Nella cartella estratta, avvia `Trama.exe` o **Trama - Tk.cmd** per l’interfaccia Classica. Per PySide6/Qt, usa **Trama - Qt.cmd**. Conserva i due avvii accanto a `Trama.exe` e alla cartella `_internal`.

Non serve installare Python. Sono supportati Windows 10 e 11 a 64 bit. Per vedere correttamente dialoghi e pulsanti è richiesto uno spazio schermo di almeno 1024 × 768 pixel.

La lingua si sceglie da **Edit → Language…** / **Modifica → Lingua…**. La scelta si applica al successivo avvio. I progetti conservano valori canonici, così il cambio di lingua non modifica le ricette.

## Un primo esperimento

Crea una tabella XY per coordinate e serie, Column per gruppi indipendenti o Grouped per esperimenti con gruppi e repliche. Seleziona una cella e incolla l'intervallo da Excel. Puoi anche importare CSV, TSV e XLSX.

Scegli un metodo da **Analyze / Analizza**, imposta le colonne e consulta i fogli dei risultati. Le analisi collegate si aggiornano dopo le modifiche dei dati. Il catalogo e i campi principali sono tradotti; parte delle tabelle dei risultati e alcuni editor specialistici restano in inglese. Una cella esclusa resta nel foglio e viene omessa dal calcolo; non viene cancellata.

Apri il grafico, usa **Format Graph / Formatta grafico** o l'Inspector per personalizzarlo. Un layout raccoglie più grafici nello stesso foglio. I risultati possono diventare nuovi dati tramite **Use Result as Data**.

Salva il progetto in formato `.alab`: mantiene tabelle, formule, esclusioni, impostazioni delle analisi, stili, layout e fogli Info. Esporta le tabelle in CSV e le figure in SVG, PDF, PNG o TIFF; per una raccolta di figure è disponibile il PDF multipagina.

## File di esempio

[Scarica il progetto dimostrativo delle schermate](examples/Laboratorio.alab). Contiene solo dati sintetici: repliche XY, un fit globale di due serie con plateau condiviso sulle medie delle repliche, un confronto grafico di trattamenti e un layout. Le stime sono dimostrative, non osservazioni sperimentali.

## Scorciatoie utili

| Azione | Scorciatoia |
| --- | --- |
| Copia / incolla | Ctrl+C / Ctrl+V |
| Incolla speciale | Ctrl+Shift+V |
| Incolla trasposto | Ctrl+Shift+T |
| Annulla / ripeti nella griglia | Ctrl+Z / Ctrl+Y |

Per migrare un progetto di un altro programma consulta la [compatibilità](compatibility.md). Per licenza, validazione e componenti inclusi consulta le [note legali](legal.md).

