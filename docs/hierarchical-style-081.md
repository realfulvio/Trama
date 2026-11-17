# Presentazione dei grafici di clustering gerarchico

Nota del ramo `grok/hierarchical-style-081`. Non è una release: `analisi/_version.py` resta `0.81.0` con `RELEASE_CHANNEL = "beta"`. Pubblicazione, merge e portabile Windows restano al coordinatore.

La sezione `run.style["hierarchical"]` cambia solo la presentazione dei dendrogrammi nativi, delle etichette, della matrice e della barra dei colori. Il fit, le distanze, l’ordine delle foglie e i fogli di risultato restano quelli del calcolo. Un’anteprima non ricalcola il clustering e non ricrea il canvas.

## Cosa resta identico

Una ricetta senza la sezione, o con sezione `{}`, disegna gli stessi artisti e la stessa geometria di prima. Nascondere un albero non toglie il suo spazio nella griglia: le altre parti non si spostano. I rapporti assenti tornano a quelli catturati dal renderer, non a un default nuovo.

La barra dei colori della matrice non è la legenda di Matplotlib e non passa dall’editor delle legende. Nasconderla collassa la sua colonna a una striscia e tiene l’asse. Le celle `imshow` possono restare raster anche in un SVG o in un layout: il layout compone i pannelli da PNG a 150 dpi. Non è un SVG interamente vettoriale.

Un override parziale eredita i valori catturati dal renderer prima della prima anteprima, non la bozza precedente. Se l’override tocca le etichette, la loro dimensione è quella della sezione gerarchica e può sostituire un `tick_size` generico su quelle stesse etichette. Senza la sezione, `tick_size` resta com’è. Solo un reset di questa sezione la toglie: titolo, assi, forme e `legend_options` restano.

`legend_options` è conservato nel formato del grafico ma non è validato qui. L’editor delle legende native è un altro incarico: i due rami si toccano in `presentation.py`, `graph_dialog.py` e nei cataloghi.

## Editor

Il pulsante **Dendrograms and heat map…** sta nella pagina del grafico, accanto all’Inspector. Lo stesso editor si apre dall’Inspector e da Format Graph. Anteprima applica la modifica solo alla figura del canvas. In Modern quella figura è la copia privata: Apply la riporta sull’originale. Annulla ed Esc rimettono la sezione confermata.

Le pagine di un componente assente sono disabilitate. Il layout è disabilitato se non c’è la mappa di calore. Una casella vuota omette il campo. Si salvano solo i campi diversi dalla cattura del renderer.

I colori dei cluster usano gli identificativi numerici già calcolati, a partire da 1. Un ramo i cui figli hanno gruppi diversi usa il colore misto. Senza un taglio, tutti i rami usano quel colore. L’editor non inventa gruppi e non rilancia il fit per colorarli.
