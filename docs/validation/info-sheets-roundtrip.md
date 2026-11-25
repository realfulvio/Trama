# Fogli Info · importazione e riapertura

Commit dell'applicazione `e95a93b20658462f4a14da143953c6dc2cceeb96`.

L'apertura in Trama, il salvataggio in un nuovo progetto ALAB e una seconda apertura danno gli stessi risultati su Windows e Linux per 72 file di riferimento. I file di partenza conservano la propria impronta SHA-256.

| Contenuto dei progetti | File | Verifica |
| --- | ---: | --- |
| XML con fogli Info | 38 | Titoli, ordine dei fogli, nomi e valori di ogni campo e testo delle note |
| Binari con fogli Info | 18 | Stessi confronti sul contenuto dei record binari |
| Archivi ZIP con fogli Info | 6 | Stessi confronti sugli oggetti dei fogli archiviati |
| Progetti privi di fogli Info | 10 | Il progetto importato e la copia ALAB riaperta hanno zero fogli Info |

I 62 file con contenuto comprendono **67 fogli, 428 coppie nome/valore e due note testuali non vuote**. I valori attesi sono stati letti nei dati di origine con un lettore di verifica indipendente dal modulo d'importazione. Gli identificatori assegnati da Trama restano stabili al salvataggio e alla riapertura. La compatibilità degli stili di note di origine resta da verificare con esempi che contengano la relativa formattazione.

In Classica Qt, all'apertura di un progetto con soli fogli Info si vede il primo foglio. Per un archivio che salva il foglio Info attivo, Trama usa quello. Se una nota di un foglio Info è illeggibile o supera il limite, l'importazione conserva titolo e campi validi e indica nella barra di stato la nota omessa. Si può salvare il contenuto recuperato in un nuovo progetto ALAB.

## Importazione di note da testo

In Vetro e Classica il test riproduce la perdita di una modifica ancora in corso quando il file di testo supera lo spazio disponibile. Sul commit indicato entrambi gli editor rifiutano il testo prima di modificare il documento. I test Qt controllano anche la cronologia di Annulla e la formattazione esistente.

Con Vetro, uno smoke aggiuntivo su Windows ha esercitato il pulsante **Importa note…** e un file UTF-8 con BOM, terminazioni CRLF e testo Unicode. Il controllo usa widget reali con il plugin Qt `windows` e fornisce al selettore il nome di un file di prova. Sono stati verificati il rifiuto a 262.145 caratteri complessivi, l'importazione al limite di 262.144, un file vuoto al limite e due Annulla distinti per l'importazione e la modifica digitata. La nota di origine mantiene il grassetto.

Su Windows sono passati i 15 test mirati e l'intero modulo della finestra Qt (63 test, con sovrapposizione tra i gruppi). Su Linux sono passati i 15 test mirati. Queste prove riguardano il codice sorgente.

## Impronte dei report

| Rapporto | SHA-256 |
| --- | --- |
| Confronto degli originali · Windows | `15ac33c58e04346e8929dfa2d6490c46e4d912ba47c687ea914ed07735724dc2` |
| Confronto degli originali · Linux | `01a8014a3b2f07f4828a4923b8d845c561a2df1168c51222f0997e5c50621704` |
| Progetti senza fogli Info · Windows | `450213ae89790b71fa31a36e5979a13a7d70910210d5dc745047359c7fcc9701` |
| Progetti senza fogli Info · Linux | `68fbdd37838a5b893e339ede09333343214763d2648d5ddd2c0593f4865e06d2` |
| Widget nativo Windows · importazione al limite | `485d10ae530cc842d760a92db9faf13e0ff452a529fc8077002f7278d5ae1e6c` |
