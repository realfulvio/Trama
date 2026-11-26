# Trama 0.112.0 beta

- **Schermata di avvio.** Opzioni e anteprima sono affiancate nelle finestre ampie. I progetti recenti si aprono con un clic e le azioni di apertura e recupero sono accanto all’elenco.
- **Dati collegati.** Collega un foglio a un CSV o TSV durante l'importazione. **File → Aggiorna da file…** mostra le modifiche, chiede come gestire i conflitti e permette di annullare l'aggiornamento. Il progetto conserva l'ultima versione confermata dei dati e si apre anche senza il file sorgente.
- **Regressione di Passing–Bablok.** Confronta due metodi di misura con pendenza, intercetta, intervalli analitici quando stimabili e, se serve, la retta d’identità.
- **Grafici per i test di rango.** Mann–Whitney e Wilcoxon producono grafici dei ranghi o delle differenze appaiate.
- **Colonne calcolate.** Le formule seguono le colonne di origine quando ne cambi il nome, anche se alimentano altre formule.
- **Iterazioni di K-means.** Il resoconto facoltativo riporta quante iterazioni sono state eseguite e perché si è fermato l'algoritmo, quando il dato è disponibile.
- **Calcoli più rapidi.** L’opzione automatica di Mann–Whitney e Wilcoxon passa prima all’approssimazione quando il test esatto supera il budget. Sono più rapidi anche la regressione di Cox, la costruzione del foglio dei punti XY e la preparazione dell’ANOVA multifattoriale.
- **Dunnett ed equazioni.** I confronti supportati contro un controllo comune usano una quadratura più precisa. I valori p aggiustati e gli intervalli possono cambiare. Le equazioni personalizzate accettano `asin`, `acos`, `atan`, `sinh`, `cosh` e `tanh`.

Estrai lo ZIP e avvia **Trama.exe** su Windows a 64 bit.

## English

- **Start screen.** Options and preview appear side by side in wide windows. Recent projects open in one click, with open and recovery commands next to the list.
- **Linked data.** Link a worksheet to a CSV or TSV during import. **File → Update from file…** previews changes, asks how to handle conflicts and supports Undo. The project keeps the last confirmed data and opens without the source file.
- **Passing–Bablok regression.** Compare two measurement methods with slope, intercept, analytical intervals when estimable and an optional identity line.
- **Rank-test plots.** Mann–Whitney and Wilcoxon can produce rank or paired-difference plots.
- **Calculated columns.** Formulas follow renamed source columns, including references in a chain of formulas.
- **K-means iterations.** The optional report shows the number of iterations and why the algorithm stopped when that information is available.
- **Faster calculations.** Automatic Mann–Whitney and Wilcoxon switch earlier to the approximation when the exact test exceeds its budget. Cox regression, XY point worksheets and preparation for multifactor ANOVA are also faster.
- **Dunnett and equations.** Supported comparisons against one common control use more accurate quadrature. Adjusted p-values and intervals may change. Custom equations support `asin`, `acos`, `atan`, `sinh`, `cosh` and `tanh`.

Extract the ZIP and open **Trama.exe** on 64-bit Windows.
