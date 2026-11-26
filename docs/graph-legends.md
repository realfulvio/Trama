# Legende dei grafici nativi

In Classica Qt apri **Cambia → Formato legenda…** (`Ctrl+Alt+L`) o fai doppio clic sulla legenda. Il doppio clic su un’etichetta porta il cursore al campo della voce corrispondente. **Cambia → Inverti ordine della legenda** inverte le voci visibili a partire dall’ordine corrente. Entrambi i comandi usano Annulla e Ripeti. L’editor è disponibile anche da **Formatta grafico → Aspetto → Formato legenda…**.

Puoi impostare un titolo, da una a otto colonne, l’ordine inverso delle voci, etichette personalizzate, cornice, sfondo, colore e larghezza del bordo e opacità. L’opacità riguarda solo cornice e sfondo: dati e testo restano leggibili. Nascondere la cornice conserva le impostazioni del bordo. Posizione, visibilità e dimensione del testo restano nei controlli già presenti in Formatta grafico.

**Applica** salva le opzioni della legenda. Se sei entrato da **Formatta grafico**, conferma anche quel dialogo. **Annulla** chiude l’editor senza applicare. Per tornare all’etichetta generata dal grafico, svuota il campo della voce. **Ripristina** rimuove le personalizzazioni di questa sezione. I pulsanti restano fuori dal corpo scorrevole della finestra.

Titolo ed etichette sono testo letterale: dollari, parentesi e caratteri Unicode non vengono interpretati come formule. Le legende multiple intenzionali, comprese quelle delle dimensioni delle bolle e le legende dell’intera figura, restano distinte. Le serie sull’asse destro restano nella legenda XY. Nei Q–Q affiancati puoi rinominare una voce del pannello normale senza modificare quello lognormale, anche dopo il ricalcolo o il cambio della distribuzione visualizzata.

Gli stili sono salvati nel progetto `.alab` e si applicano ai grafici ricalcolati, ai layout e agli export. Le impostazioni di voci temporaneamente assenti rimangono memorizzate. Una figura senza legenda non ne riceve una inventata. Le anteprime archiviate o raster senza artisti nativi non sono modificabili con questo editor.

## Stato canonico

La presentazione è in `run.style["legend_options"]` e in `Dataset.graph_styles`, separata dalla ricetta statistica. I valori salvati non dipendono dalla lingua dell’interfaccia. Le ricette senza questa sezione conservano il comportamento precedente.

La mappa `labels` identifica serie e gruppi con le chiavi del grafico, gruppi tipizzati con `group:<tipo>:<valore>` e voci senza artisti identificabili con `entry:<ambito>#<indice originale>`. Le voci dei pannelli secondari e dei Q–Q usano `scope:<ambito codificato URL>:<chiave originale>`: i due pannelli Q–Q hanno ambiti `qq:normal` e `qq:lognormal`, indipendenti dalla posizione degli assi. Il riferimento Q–Q usa l’identità dell’artista, anziché il testo che contiene coefficienti variabili. Invertire le voci non cambia queste identità.

I nuovi stili richiedono una versione dell’applicazione che riconosca `legend_options`. Conserva una copia del progetto prima di usarlo con versioni precedenti.
