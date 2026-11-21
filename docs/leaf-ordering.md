# Ordine ottimale delle foglie

Nel raggruppamento gerarchico l'albero dice chi si fonde con chi e a che altezza, ma non dice in che ordine disegnare i due rami di ogni fusione: scambiare i figli di un nodo dà lo stesso albero. Con **Ordine delle foglie** (*Leaf ordering*) scegli l'ordine con cui le righe e le colonne compaiono nel dendrogramma, nelle etichette e nelle celle della mappa di calore.

| Valore | Significato |
| --- | --- |
| **Predefinito** (*Default*) | L'ordine storico di Trama: figli nell'ordine della fusione. È il valore se il campo manca, quindi le ricette e i progetti vecchi si riaprono con gli stessi fogli e la stessa figura. |
| **Ottimale** (*Optimal*) | Fra tutti gli ordini ottenibili scambiando i figli dei nodi sceglie quello con **costo minimo**: la somma delle distanze fra foglie adiacenti. Mette vicini i profili simili. |

Il campo sta nelle opzioni del raggruppamento gerarchico, dopo **Distanza**. Il progetto salva il valore inglese (`Default`, `Optimal`), quindi una ricetta si riapre uguale in qualunque lingua.

## Cosa cambia e cosa no

Cambia solo l'ordine di disegno. Non cambiano il clustering (c'è un solo fit per asse), le fusioni, le altezze, i tagli, le assegnazioni ai gruppi e il loro numero: il foglio **Assignments** resta quello del calcolo originale anche quando un altro orientamento darebbe una numerazione diversa a un taglio nuovo. Le distanze usate sono le stesse del fit, con la metrica e la scala della ricetta, per ogni asse attivo: righe, colonne o entrambi.

## Fogli dei risultati

Con **Ottimale** compaiono tre fogli (con un solo asse attivo il nome porta solo quell'asse). I nomi sono inglesi fissi, come nelle altre analisi:

- **Row leaf order** e **Column leaf order**: **Position** (da 1), **Label**, **Input index** (la posizione della foglia in ingresso, da 1) e **Distance from previous** (vuota per la prima foglia). La somma di quest'ultima colonna è il costo finale. L'indice in ingresso identifica la foglia anche con etichette duplicate o con caratteri speciali: l'etichetta è solo un testo da leggere, mai un'identità.
- **Leaf order costs**: per ogni asse **Leaves**, **Original cost** (costo dell'ordine predefinito) e **Final cost**.

Con **Predefinito** i fogli sono esattamente quelli di prima, senza questi tre.

## Il grafico

Dendrogrammi, etichette e celle seguono lo stesso ordine del foglio, anche nel grafico collegato **Grafico del raggruppamento gerarchico** (*Hierarchy graph*), nell'Inspector, in un layout a due pannelli e nelle esportazioni vettoriali PDF e SVG (la mappa di calore e la barra colori restano immagini raster, come prima). Applicare uno stile o girare il dendrogramma in orizzontale da un grafico collegato non rifà il clustering né l'ordinamento: l'ordine arriva dal risultato già calcolato.

## Esempio: stessa matrice, prima e dopo

I dati sono i sette campioni sintetici di `tests/data/leaf_order/profili-sintetici.csv`, con criterio di collegamento *media* e distanza *cityblock* (Manhattan), senza scala. Costo delle righe 559 → **520**, delle colonne 519 → **492**.

Ordine **Predefinito**:

| Riga | Cold | Oxygen | Salt | Warm | Light |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sample 3 | -21 | 12 | -5 | -22 | -6 |
| Sample 2 | 20 | 20 | -21 | 1 | 1 |
| Sample 4 | 21 | 1 | -5 | -30 | 28 |
| Sample 6 | 5 | 25 | 15 | 27 | 20 |
| Sample 7 | -22 | -22 | 21 | 26 | 29 |
| Sample 1 | 17 | -18 | -14 | 28 | 18 |
| Sample 5 | -16 | -10 | -26 | 20 | 15 |

Ordine **Ottimale**:

| Riga | Cold | Oxygen | Salt | Light | Warm |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sample 3 | -21 | 12 | -5 | -6 | -22 |
| Sample 4 | 21 | 1 | -5 | 28 | -30 |
| Sample 2 | 20 | 20 | -21 | 1 | 1 |
| Sample 1 | 17 | -18 | -14 | 18 | 28 |
| Sample 5 | -16 | -10 | -26 | 15 | 20 |
| Sample 7 | -22 | -22 | 21 | 29 | 26 |
| Sample 6 | 5 | 25 | 15 | 20 | 27 |

Il foglio **Row leaf order** riporta le distanze fra righe adiacenti 95 + 94 + 92 + 64 + 85 + 90 = 520; **Column leaf order**, 114 + 137 + 142 + 99 = 492.

## Come funziona

Il metodo è quello di Bar-Joseph, Gifford e Jaakkola (2001): una programmazione dinamica sull'albero che per ogni nodo tiene il costo migliore per ogni coppia di foglie agli estremi del suo ordine. Il risultato è esatto, non un'euristica, e il tempo cresce al più come n³. Le fusioni vengono processate dal basso, i prodotti min-plus vanno a blocchi con il GIL rilasciato e il controllo di annullamento è fra un blocco e l'altro.

**Perché non `scipy.cluster.hierarchy.optimal_leaf_ordering`.** Trama l'ha provata contro l'enumerazione esaustiva di tutti i ribaltamenti dell'albero. Con scipy 1.18.1 il risultato non sempre è minimo: su quattro osservazioni con le distanze di `tests/test_leaf_order.py` (`FOUR`) scipy dà l'ordine 0, 2, 3, 1 con costo 3,727, mentre il minimo è 3,192 (ordine 0, 3, 2, 1). In più è una chiamata unica che tiene il GIL: non si può annullare e blocca il thread dell'interfaccia. Per questo Trama usa un ottimizzatore proprio, verificato contro l'enumerazione su 240 casi casuali (undici combinazioni di criterio di collegamento e distanza, con pareggi e righe ripetute) e contro l'oracolo del pacchetto.

## Pareggi e ripetibilità

A parità di costo più ordini sono validi, uno e il suo ribaltamento compresi. Trama sceglie sempre lo stesso sullo stesso input: se l'ordine predefinito è già ottimo lo lascia com'è, altrimenti, fra i minimi, prende il primo nell'ordine delle foglie (soglia di parità 10⁻¹² in valore relativo). Un risultato diverso per ribaltamento non è quindi un errore, e lo stesso progetto riaperto dà lo stesso ordine.

## Limiti e tempi

Il limite è **2000 foglie per asse**. Il controllo avviene prima di allocare qualsiasi matrice, quando premi **Esegui analisi**: se lo superi il dialogo si riapre sul campo **Ordine delle foglie** con il messaggio «L’ordine ottimale delle foglie è limitato a 2000 foglie per asse. Usa meno osservazioni o variabili, oppure scegli Predefinito.» Con **Predefinito** non c'è alcun limite.

Misure su dati sintetici (12 variabili normali, criterio *media*, distanza euclidea), un processo Python, una macchina Windows 10 con la CPU già occupata da altri programmi, quindi tempi prudenti. L'albero a pettine è il caso con la massima profondità (criterio *single* su punti allineati):

| Foglie | Albero | Tempo | RAM di picco (prima dell'ordinamento) |
| ---: | --- | ---: | ---: |
| 1000 | bilanciato | 0,38 s | 173 MB (152 MB) |
| 2000 | bilanciato | 2,6 s | 234 MB (174 MB) |
| 3000 | bilanciato | 5,1 s | 333 MB (212 MB) |
| 2000 | a pettine | 0,6 s | 235 MB (160 MB) |

L'ordinamento gira nel thread di calcolo come il resto dell'analisi: la finestra non si blocca, la barra di stato mostra l'attività e **Annulla** si ferma fra un blocco e l'altro. Misurato nello smoke dedicato su 1200 righe, l'annullamento risponde in 0,03–0,09 s; un'analisi annullata non aggiunge nulla al progetto e un ricalcolo annullato lascia ricetta e risultato precedenti.

## Esempio nel programma

Apri `tests/data/leaf_order/profili-sintetici.csv`, scegli **Analizza → Raggruppamento → Raggruppamento gerarchico**, imposta **Direzione** su *Righe e colonne*, **Distanza** su *cityblock* e **Ordine delle foglie** su *Ottimale*. Con *Predefinito* ottieni la prima matrice, con *Ottimale* la seconda.

## Riferimenti

- Bar-Joseph Z, Gifford DK, Jaakkola TS. [Fast optimal leaf ordering for hierarchical clustering](https://doi.org/10.1093/bioinformatics/17.suppl_1.S22). Bioinformatics, 2001.
- [`scipy.cluster.hierarchy.optimal_leaf_ordering`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.cluster.hierarchy.optimal_leaf_ordering.html).
