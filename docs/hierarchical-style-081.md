# Presentazione dei grafici di clustering gerarchico

La sezione `run.style["hierarchical"]` cambia solo la presentazione dei dendrogrammi nativi, delle etichette, della matrice e della barra dei colori. Il fit, le distanze, l’ordine delle foglie e i fogli di risultato restano quelli del calcolo. Un’anteprima non ricalcola il clustering e non ricrea il canvas.

## Cosa resta identico

Una ricetta senza la sezione, o con sezione `{}`, disegna gli stessi artisti e la stessa geometria di prima. Nascondere un albero non toglie il suo spazio nella griglia: le altre parti non si spostano. I rapporti assenti tornano a quelli catturati dal renderer, non a un default nuovo.

La barra dei colori si modifica nello stesso editor della mappa. Quando la nascondi, il layout riduce lo spazio che occupa. I rami restano allineati alle celle anche con la barra orizzontale o con celle quadrate. L’anteprima del layout usa immagini dei pannelli a 150 dpi. L’export SVG da **Esporta con opzioni** conserva testi, assi e dendrogrammi come elementi vettoriali e incorpora le celle della mappa come immagine.

Un override parziale eredita i valori catturati dal renderer prima della prima anteprima, non la bozza precedente. Se l’override tocca le etichette, la loro dimensione è quella della sezione gerarchica e può sostituire un `tick_size` generico su quelle stesse etichette. Senza la sezione, `tick_size` resta com’è. Solo un reset di questa sezione la toglie: titolo, assi, forme e `legend_options` restano.

`legend_options` resta la sezione dell’editor delle legende già su main: la valida quel modulo, non questo. La barra dei colori della matrice non entra in quella sezione. Un reset del solo formato gerarchico lascia titolo, assi, forme e `legend_options`. Il reset di Format Graph segue l’editor delle legende per `legend_options` e conserva la sezione gerarchica.

## Editor

In Qt, apri **Dendrogrammi e mappa di calore…** dall’Inspector o dalla scheda **Aspetto** di **Formato grafico**. Usa **Anteprima** per vedere la modifica. **Applica** trasferisce le scelte all’editor che hai aperto. Conferma anche lì per salvarle nel progetto. Per un dendrogramma standalone trovi solo la pagina dell’albero disponibile. Nella mappa raggruppata trovi anche la barra dei colori e, dove sono presenti gli alberi, le loro proporzioni.

Nell’interfaccia classica il pulsante **Dendrograms and heat map…** è anche nella pagina del grafico. Lo stesso editor si apre dall’Inspector e da Format Graph. L’anteprima agisce sulla figura del canvas. Annulla ed Esc ripristinano la vista iniziale dell’editor.

Le pagine di un componente assente sono nascoste in Qt e disabilitate nell’interfaccia classica. Le proporzioni del layout sono disponibili per le mappe con alberi. Una casella vuota ripristina il valore del renderer.

I colori dei cluster usano gli identificativi numerici già calcolati, a partire da 1. Un ramo i cui figli hanno gruppi diversi usa il colore misto. Senza un taglio, tutti i rami usano quel colore. L’editor non inventa gruppi e non rilancia il fit per colorarli.

Il grafico del gomito usa la formattazione generale. Lo stile gerarchico rimane nella ricetta e torna visibile quando selezioni di nuovo il dendrogramma o la mappa.
