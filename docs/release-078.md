# Trama 0.78.0 beta — FDR e riferimenti degli assi

- **Control false discoveries:** BH, BY e BKY a due stadi su più colonne p, con famiglie esplicite, dati mancanti distinti e grafico diagnostico facoltativo. I p aggiustati BKY dipendono dal livello scelto; quelli BH/BY sono indipendenti dal livello.
- **Tacche, linee e fasce:** nuovi editor con anteprima per assi numerici primari lineari o logaritmici, etichette letterali e conservazione in SVG/PDF e layout nativi.
- **Risultati precedenti protetti:** se un ricalcolo FDR fallisce, l'ultimo risultato riuscito resta riconoscibile come precedente e non può essere esportato o riutilizzato fino alla correzione dei dati.
- **Esportazione corretta:** le tacche sul bordo opposto che si trovano fuori dalla vista non allargano più il ritaglio della figura.

Tutte le versioni 0.x rimangono beta. Le nuove guide descrivono gli ambiti supportati e i limiti: in particolare le etichette sul bordo opposto possono sovrapporsi a quelle di un secondo asse Y; non è dichiarata una gestione automatica delle collisioni. Il Tema standard e il Tema Moderno rimangono disponibili.

[Guida FDR e schermata Windows](fdr-control.md) · [Guida agli assi](axis-guides.md) · [Collaudi](validation-078.md)
