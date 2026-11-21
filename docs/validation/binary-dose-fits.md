# Ricalcolo dei fit dose-risposta nei progetti binari PZT

La verifica copre due progetti con una serie Y per tabella, uno di inibizione e uno di stimolazione. Trama importa le osservazioni, le tabelle di risultato salvate e le ricette identificabili dai parametri del calcolo. Ogni progetto contiene due ascisse, concentrazione e logaritmo decimale della concentrazione. Ciascuna ha una normalizzazione minimo–massimo e quattro fit, con pendenza standard o variabile su dati grezzi o normalizzati.

## Risultati

| Prova | Inibizione | Stimolazione |
|---|---:|---:|
| Fit confrontati con i coefficienti e la somma dei quadrati dei residui archiviati | 8 | 8 |
| Massimo scarto relativo della somma dei quadrati | 0,0233% | 0,0085% |
| Valori normalizzati identici alle tabelle del progetto | 18/18 | 18/18 |
| Fit ricalcolati con esito diverso dopo la modifica di una misura nella tabella logaritmica | 4/4 | 4/4 |
| Fit della seconda tabella con esito identico dopo la modifica | 4/4 | 4/4 |

Il controllo apre ciascun progetto nella finestra Qt, visita i fogli generati, modifica una misura, salva in formato ALAB e riapre il file in una nuova finestra. Tutti i coefficienti e le somme dei quadrati ricalcolati sono identici prima e dopo la riapertura. Il controllo esporta anche il grafico del modello normalizzato a pendenza variabile. Gli hash dei due file di origine rimangono identici.

Il commit di codice `83dba361115eb82a538c42949786a31bb45bffc9` ha superato 66 test dell’importatore binario su Linux e Windows. Su Windows sono stati provati sia il backend PySide6 nativo sia la finestra Classica Tk, con widget pilotati da codice. In Classica, per ciascun progetto, sono stati ripetuti l’apertura dei risultati, la modifica di una misura, il salvataggio e il controllo di tutti gli otto fit dopo la riapertura. Il confronto fra versione precedente e candidata su 66 progetti PZT conserva contenuto delle tabelle e fogli Info di tutti gli esempi. Solo i due progetti descritti acquistano ricette.

## Limiti della verifica

Le prove riguardano profili noti a una sola serie, senza pesi, con collegamenti univoci fra misura, tabella normalizzata e fit. Le impostazioni di modello e vincoli sconosciute mantengono i risultati archiviati quando leggibili. Le stime originali visualizzate hanno precisione finita. Il collaudo del sorgente su Windows è distinto dal collaudo di un futuro portabile che contenga la modifica.
