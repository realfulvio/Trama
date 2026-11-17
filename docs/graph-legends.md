# Legende dei grafici nativi

Apri **Formatta grafico → Aspetto → Formato legenda…**, oppure lo stesso pulsante nella sezione Pagina dell’Inspector. L’editor modifica la presentazione senza ripetere l’analisi statistica.

Puoi impostare un titolo, da una a otto colonne, l’ordine inverso delle voci, etichette personalizzate, cornice, sfondo, colore e larghezza del bordo e opacità. L’opacità riguarda solo cornice e sfondo: dati e testo restano leggibili. Nascondere la cornice conserva le impostazioni del bordo. Posizione, visibilità e dimensione del testo restano nei controlli già presenti in Formatta grafico.

**Anteprima** aggiorna la figura. **Annulla** ripristina lo stato precedente. **Applica** accetta le opzioni nell’editor; conferma anche Formatta grafico o l’Inspector per salvarle nello stile. **Ripristina** rimuove le personalizzazioni di questa sezione. I pulsanti restano fuori dal corpo scorrevole della finestra.

Titolo ed etichette sono testo letterale: dollari, parentesi e caratteri Unicode non vengono interpretati come formule. Le legende multiple intenzionali, comprese quelle delle dimensioni delle bolle e le legende dell’intera figura, restano distinte. Le serie sull’asse destro restano nella legenda XY. Nei Q–Q affiancati puoi rinominare una voce del pannello normale senza modificare quello lognormale, anche dopo il ricalcolo o il cambio della distribuzione visualizzata.

Gli stili sono salvati nel progetto `.alab` e si applicano ai grafici ricalcolati, ai layout e agli export. Le impostazioni di voci temporaneamente assenti rimangono memorizzate. Una figura senza legenda non ne riceve una inventata. Le anteprime archiviate o raster senza artisti nativi non sono modificabili con questo editor.

## Stato canonico

La presentazione è in `run.style["legend_options"]` e in `Dataset.graph_styles`, separata dalla ricetta statistica. I valori salvati non dipendono dalla lingua dell’interfaccia. Le ricette senza questa sezione conservano il comportamento precedente.

La mappa `labels` identifica serie e gruppi con le chiavi del grafico, gruppi tipizzati con `group:<tipo>:<valore>` e voci senza artisti identificabili con `entry:<ambito>#<indice originale>`. Le voci dei pannelli secondari e dei Q–Q usano `scope:<ambito codificato URL>:<chiave originale>`: i due pannelli Q–Q hanno ambiti `qq:normal` e `qq:lognormal`, indipendenti dalla posizione degli assi. Il riferimento Q–Q usa l’identità dell’artista, anziché il testo che contiene coefficienti variabili. Invertire le voci non cambia queste identità.

I nuovi stili richiedono una versione dell’applicazione che riconosca `legend_options`. Conserva una copia del progetto prima di usarlo con versioni precedenti.
