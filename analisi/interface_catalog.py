"""Common interface captions only; never apply these to worksheet or user text.

English strings are stable display/dispatch identifiers. i18n registers this catalog at
startup, and individual controls explicitly request a caption or bind fixed choices.
"""

# A line-based catalog keeps the English source beside its Italian translation.
# Names of tests, people, algorithms and mathematical notation are retained where appropriate.
_TEXT = """
Mann–Whitney|Mann–Whitney
Kruskal–Wallis|Kruskal–Wallis
Friedman|Friedman
Bland–Altman|Bland–Altman
Kolmogorov–Smirnov|Kolmogorov–Smirnov
Analyze Data|Analizza dati
Find an analysis|Cerca un’analisi
Run Analysis|Esegui analisi
Fit and curve range|Intervalli X
Show observations outside fit|Mostra osservazioni fuori dal fit
Fit X minimum|X minimo per il fit
Fit X maximum|X massimo per il fit
Curve X minimum|X minimo della curva
Curve X maximum|X massimo della curva
Curve points|Punti della curva
Enter a finite X value or leave this field empty.|Inserisci un valore X finito oppure lascia vuoto il campo.
Choose a whole number from 2 to 2000.|Scegli un numero intero da 2 a 2000.
The maximum X must be greater than the minimum X.|X massimo deve essere maggiore di X minimo.
No observations fall within the fit X range.|Nessuna osservazione rientra nell’intervallo X del fit.
The X column must contain real, finite values.|La colonna X deve contenere valori reali e finiti.
The drawn curve needs a maximum X greater than its minimum X.|Per disegnare la curva, X massimo deve essere maggiore di X minimo.
The model must predict finite values on the drawn curve.|Il modello deve produrre valori finiti nell’intervallo della curva.
The drawn curve for this model requires positive X values.|La curva di questo modello richiede X positivi.
The drawn curve for this model requires nonnegative X values.|La curva di questo modello richiede X non negativi.
Cancel|Annulla
OK|OK
Apply|Applica
Close|Chiudi
Add|Aggiungi
Remove|Rimuovi
Up|Su
Down|Giù
Pick…|Scegli…
Browse…|Sfoglia…
Check parameters|Controlla i parametri
Variables|Variabili
Options|Opzioni
Comparisons|Confronti
Multiple comparisons|Confronti multipli
Status coding|Codifica degli eventi
Effect sizes|Dimensioni dell’effetto
Ellipse|Ellisse
Fill and border|Riempimento e bordo
Select columns|Seleziona colonne
Select rows|Seleziona righe
Transform columns|Trasforma colonne
Worksheet|Foglio dati
Tests and graph|Test e grafico
Multiplicity|Confronti multipli
Subcolumns|Sottocolonne
Model and inference|Modello e inferenza
Graph options|Opzioni del grafico
Color mapping|Mappatura dei colori
Scale and reference|Scala e riferimento
Table|Tabella
Test and effects|Test ed effetti
Comparison|Confronto
Data|Dati
Output|Risultati
Data arrangement|Organizzazione dei dati
Output format|Formato dei risultati
Columns|Colonne
Rows|Righe
Result|Risultato
Function|Funzione
Study|Studio
Design|Disegno
Model and status|Modello e stato
Method|Metodo
Curves|Curve
Equation|Equazione
Parameters|Parametri
Series constraints|Vincoli delle serie
Data Processing|Elaborazione dei dati
Data Exploration and Summary|Esplorazione e sintesi dei dati
Regression and Curves|Regressione e curve
Group Comparison|Confronto tra gruppi
Survival Analysis|Analisi di sopravvivenza
Clustering|Raggruppamento
Graphing|Grafici
Study Design and Simulation|Disegno degli studi e simulazione
Descriptive statistics|Statistica descrittiva
Tolerance intervals|Intervalli di tolleranza
Normality tests|Test di normalità
t-test|Test t
Paired t-test (columns)|Test t appaiato (colonne)
Lognormal t-test|Test t lognormale
Compare two variances|Confronta due varianze
Show variance comparison|Mostra il confronto delle varianze
Variance ratio|Rapporto tra le varianze
SD ratio|Rapporto tra le DS
Equivalence test (TOST)|Test di equivalenza (TOST)
Permutation test for mean difference|Test di permutazione per la differenza tra medie
Yuen's test for trimmed means|Test di Yuen per medie troncate
Brunner–Munzel test|Test di Brunner–Munzel
Lower margin|Margine inferiore
Upper margin|Margine superiore
Wilcoxon signed-rank|Test dei ranghi con segno di Wilcoxon
Mood median test|Test delle mediane di Mood
Correlation|Correlazione
Correlation matrix|Matrice di correlazione
Partial correlation|Correlazione parziale
Covariates|Covariate
Holm adjustment|Correzione di Holm
Residual scatter|Grafico dei residui
Multiple tests (one per row)|Test multipli (uno per riga)
Nested t test|Test t annidato
Nested one-way ANOVA|ANOVA a una via annidata
Contingency table|Tabella di contingenza
Paired proportions|Proporzioni appaiate
Parts of whole graph|Grafico delle parti di un intero
Compare observed distribution with expected|Confronta distribuzione osservata e attesa
Linear regression|Regressione lineare
Compare regression lines|Confronta rette di regressione
Nonlinear regression|Regressione non lineare
Compare nonlinear models|Confronta modelli non lineari
Compare models (AICc)|Confronta modelli (AICc)
Multifactor ANOVA|ANOVA multifattoriale
Result significant digits (0 = automatic)|Cifre significative nei risultati (0 = automatico)
P-value display|Visualizzazione dei valori p
P-value decimal places|Cifre decimali dei valori p
P-value decimals|Valore p con decimali fissi
Significance stars|Asterischi di significatività
P value and significance stars|Valore p e asterischi di significatività
Planned contrasts…|Contrasti pianificati…
Planned contrast weights|Pesi dei contrasti pianificati
No inference|Nessuna inferenza
Not estimable|Non stimabile
Grouped two-way ANOVA|ANOVA a due fattori da dati raggruppati
Row factor name|Nome del fattore riga
Column factor name|Nome del fattore colonna
Include interaction|Includi interazione
Kaplan–Meier survival|Sopravvivenza di Kaplan–Meier
K-means model selection|Selezione del modello k-means
K-means clustering|Raggruppamento k-means
Column scaling|Scala delle colonne
Standardized|Standardizzate
Unscaled|Originali
Choose a supported K-means column scaling.|Scegli come scalare le colonne per il k-means.
Choose a supported Gap reference geometry.|Scegli la geometria del riferimento Gap.
K-means algorithm|Algoritmo k-means
K-means initialization|Inizializzazione k-means
Best of 10 starts|Migliore di 10 partenze
K-means++|K-means++
Choose a K-means initialization.|Scegli l'inizializzazione k-means.
Lloyd|Lloyd
Forgy–Lloyd|Forgy–Lloyd
Hartigan–Wong|Hartigan–Wong
MacQueen|MacQueen
Hartigan–Wong iteration limit|Limite di iterazioni Hartigan–Wong
MacQueen iteration limit|Limite di iterazioni MacQueen
Lloyd iteration limit|Limite di iterazioni Lloyd
Initial worksheet rows|Righe iniziali del foglio
Report cluster details|Mostra i dettagli dei gruppi
Report standardized observations|Mostra le osservazioni standardizzate
Report scaled observations|Mostra le osservazioni scalate
Report assigned distances|Mostra le distanze dal centro assegnato
Report initial centroids|Mostra i centri iniziali
Report cluster ANOVA|Mostra l’ANOVA descrittiva dei gruppi
Report assignments for every k|Mostra le assegnazioni per ogni k
Report Gap statistics|Mostra le statistiche Gap
Report K-means fit diagnostics|Mostra il resoconto delle iterazioni k-means
K-means fit diagnostics|Iterazioni k-means
Iterations|Iterazioni
Stop reason|Motivo dell’arresto
Fit source|Origine del modello
Converged|Convergenza raggiunta
Iteration limit reached|Limite di iterazioni raggiunto
Fixed passes completed|Passaggi programmati completati
Current fit|Calcolo corrente
Saved fit|Modello salvato
Not recorded|Non registrato
Choose whether to include this report.|Scegli se includere questo report.
Show WSS plot|Mostra il grafico WSS
Show silhouette plot|Mostra il grafico della silhouette
Show Gap plot|Mostra il grafico Gap
K-means metric plot|Grafico delle metriche k-means
Cluster metric|Metrica del raggruppamento
Choose a linked result from K-means model selection.|Scegli un risultato collegato della selezione del modello k-means.
Choose a K-means metric.|Scegli una metrica k-means.
The source analysis does not provide this metric.|L’analisi di origine non fornisce questa metrica.
Choose whether to show this plot.|Scegli se mostrare questo grafico.
Enter a whole number from 1 to 1000.|Inserisci un intero da 1 a 1000.
Enter one distinct worksheet row per cluster, separated by commas.|Inserisci una riga distinta del foglio per ogni gruppo, separando i numeri con virgole.
Each initial worksheet row must exist and have all selected values.|Ogni riga iniziale deve esistere e contenere tutti i valori selezionati.
Initial observations must specify distinct centers.|Le osservazioni iniziali devono individuare centri distinti.
Choose a K-means algorithm.|Scegli un algoritmo k-means.
Hartigan–Wong reached the maximum number of iterations.|Hartigan–Wong ha raggiunto il limite di iterazioni.
MacQueen reached the maximum number of iterations.|MacQueen ha raggiunto il limite di iterazioni.
Hierarchical clustering|Raggruppamento gerarchico
Hierarchy graph|Grafico del raggruppamento gerarchico
Choose a linked Merges result from hierarchical clustering.|Scegli un risultato Merges collegato a un raggruppamento gerarchico.
Choose a hierarchy graph type.|Scegli un tipo di grafico per il raggruppamento gerarchico.
Choose an axis fitted by the source hierarchy.|Scegli un asse calcolato dal raggruppamento sorgente.
Leaf ordering|Ordine delle foglie
Optimal|Ottimale
Choose Default or Optimal leaf ordering.|Scegli l’ordine delle foglie Predefinito oppure Ottimale.
Optimal leaf ordering is limited to 2000 leaves per axis. Use fewer observations or variables, or choose Default.|L’ordine ottimale delle foglie è limitato a 2000 foglie per asse. Usa meno osservazioni o variabili, oppure scegli Predefinito.
Scatter / confidence ellipse|Dispersione / ellisse di confidenza
Column graph|Grafico a colonne
Heat map|Mappa di calore
Grouped graph|Grafico raggruppato
XY error bars|Barre di errore XY
XY series|Serie XY
Histogram|Istogramma
Frequency distribution|Distribuzione di frequenza
Box / violin plot|Grafico a scatola / violino
Grouped distribution plot|Distribuzioni raggruppate
Bubble plot|Grafico a bolle
Before/after|Prima/dopo
Subject trajectories|Traiettorie dei soggetti
Forest plot|Grafico forest
Meta-analysis of effect estimates|Meta-analisi delle stime
Identify outliers|Individua valori anomali
Monte Carlo study|Studio Monte Carlo
Select and Transform|Seleziona e trasforma
Row filters|Filtri delle righe
Calculated variables|Variabili calcolate
Calculated variable|Variabile calcolata
New variable|Nuova variabile
Comparison variable|Variabile di confronto
Variable|Variabile
Condition|Condizione
Compare to|Confronta con
Number|Numero
Text|Testo
Value|Valore
Formula|Formula
Is missing|È mancante
Is not missing|È presente
New filter|Nuovo filtro
Rows must satisfy all the filters. Leave the list empty to use the row range.|Le righe devono soddisfare tutti i filtri. Lascia vuoto l'elenco per usare l'intervallo di righe.
Formulas use the selected rows and run from top to bottom.|Le formule usano le righe selezionate e vengono valutate dall'alto verso il basso.
choose an existing variable.|scegli una variabile esistente.
choose a numeric variable for a number comparison.|scegli una variabile numerica per il confronto.
enter a finite number.|inserisci un numero finito.
enter a finite number within the floating-point range.|inserisci un numero finito nell'intervallo rappresentabile.
compare two variables of the same type.|confronta due variabili dello stesso tipo.
text comparisons support only = and !=.|per il testo usa = o !=.
choose an operator and enter a comparison value.|scegli un operatore e inserisci un valore di confronto.
enter a name of up to 160 characters.|inserisci un nome di al massimo 160 caratteri.
Choose distinct existing variables.|Scegli variabili esistenti e distinte.
Choose at least one output column or calculated variable.|Scegli almeno una colonna in uscita o una variabile calcolata.
First row must be a row number from 1 to 2,000,000, or blank.|La prima riga deve essere un intero da 1 a 2.000.000. Puoi anche lasciare vuoto il campo.
Last row must be a row number from 1 to 2,000,000, or blank.|L'ultima riga deve essere un intero da 1 a 2.000.000. Puoi anche lasciare vuoto il campo.
Last row must be at or after the first row.|L'ultima riga deve essere uguale o successiva alla prima.
Invalid formula syntax.|Sintassi della formula non valida.
Unknown column:|Colonna sconosciuta:
Transpose X and Y|Trasponi X e Y
Extract and rearrange|Estrai e riorganizza
Mixed-effects model (REML)|Modello a effetti misti (REML)
Global nonlinear regression|Regressione non lineare globale
Transform concentrations (X)|Trasforma concentrazioni (X)
Remove baseline and column math|Sottrai riferimento e calcola tra colonne
Prune rows|Filtra e aggrega righe
Fraction of total|Frazione del totale
One-way ANOVA|ANOVA a una via
Repeated measures ANOVA|ANOVA a misure ripetute
ROC curve|Curva ROC
Compare paired ROC curves|Confronta curve ROC appaiate
Deming regression|Regressione di Deming
Passing–Bablok regression|Regressione di Passing–Bablok
Area under curve|Area sotto la curva
Interpolate a standard curve|Interpola una curva di calibrazione
Fit spline/LOWESS|Adatta spline/LOWESS
Smooth / differentiate / integrate|Smussa / deriva / integra
Plot a function|Traccia una funzione
Robust curve fit|Adattamento robusto di curve
Fit custom equation|Adatta un’equazione personalizzata
Global fit custom equation|Adattamento globale di un’equazione personalizzata
Principal component analysis|Analisi delle componenti principali
Multiple regression|Regressione multipla
Negative binomial regression|Regressione binomiale negativa
Cox regression|Regressione di Cox
Competing risks|Rischi competitivi
Multiple t-tests|Test t multipli
Adjust a stack of p values|Correggi una serie di valori p
Normalize|Normalizza
Transform|Trasforma
Row statistics|Statistiche per riga
Reshape replicates|Riorganizza repliche
Outlier test (Grubbs)|Test dei valori anomali (Grubbs)
Power and sample size|Potenza e dimensione del campione
Simulate data|Simula dati
Response|Risposta
Group|Gruppo
Category|Categoria
Split by|Dividi per
Subject|Soggetto
Null mean|Media sotto l’ipotesi nulla
First|Prima variabile
Second|Seconda variabile
X|X
Y|Y
Input format|Formato dei dati
Input|Dati in ingresso
Missing values|Valori mancanti
R² heat map|Mappa di calore di R²
First replicates|Repliche della prima variabile
Second replicates|Repliche della seconda variabile
First mean|Media della prima variabile
First error|Errore della prima variabile
First N|N della prima variabile
Second mean|Media della seconda variabile
Second error|Errore della seconda variabile
Second N|N della seconda variabile
Row labels|Etichette delle righe
Row label|Etichetta della riga
Test|Test
Correction|Correzione
Family alpha|Alfa della famiglia
False discovery rate (%)|Tasso di false scoperte (%)
Stacked subcolumns|Sottocolonne impilate
Each subcolumn is an independent unit|Ogni sottocolonna è un’unità indipendente
Denominator method|Metodo del denominatore
Post-hoc|Confronti post hoc
Count columns|Colonne dei conteggi
Row titles|Titoli delle righe
Blank cells|Celle vuote
Fisher alternative|Ipotesi alternativa di Fisher
Monte Carlo samples|Campioni Monte Carlo
Seed|Seme casuale
Odds ratio interval|Intervallo dell’odds ratio
Relative risk interval|Intervallo del rischio relativo
Diagnostic measures|Misure diagnostiche
Diagnostic interval|Intervallo diagnostico
Values|Valori
Graph style|Stile del grafico
Legend|Legenda
Reverse order|Inverti ordine
Show total|Mostra totale
Observed counts|Conteggi osservati
Expected distribution|Distribuzione attesa
Expected values|Valori attesi
Estimated parameters|Parametri stimati
Test method|Metodo del test
Exact binomial|Binomiale esatto
Residual diagnostics|Diagnostica dei residui
Band|Banda
Y columns|Colonne Y
Model view|Vista del modello
Grouping variables|Variabili di raggruppamento
Model|Modello
Weighting|Ponderazione
SD column|Colonna della deviazione standard
Runs test|Test delle sequenze
Replicate lack of fit|Mancato adattamento tra repliche
Residuals versus X|Residui rispetto a X
Nested models|Modelli annidati
Models|Modelli
Show graph|Mostra grafico
Factors|Fattori
Interaction order|Ordine delle interazioni
Compare marginal means by|Confronta medie marginali per
Cell comparison factors|Fattori dei confronti tra celle
Within factors (simple effects)|Entro i fattori (effetti semplici)
Families|Famiglie
Reverse comparisons|Inverti confronti
Time|Tempo
Event columns|Colonne degli eventi
Pairwise tests|Test a coppie
Pairwise correction|Correzione dei confronti a coppie
Pairwise control group|Gruppo di controllo per i confronti
Show adjusted pairwise p|Mostra p aggiustati per i confronti
Pairwise alpha|Alfa per i confronti a coppie
Median method|Metodo della mediana
Log-rank trend|Tendenza log-rank
Trend group order|Ordine dei gruppi per la tendenza
Hazard ratio|Rapporto dei rischi (HR)
Hazard ratio numerator|Numeratore del rapporto dei rischi
Event code|Codice dell’evento
Censor code|Codice di censura
Other status values|Altri valori di stato
Curve|Curva
Display units|Unità visualizzate
Observation markers|Simboli delle osservazioni
Uncertainty|Incertezza
Interval method|Metodo dell’intervallo
Show risk table below graph|Mostra tabella dei soggetti a rischio sotto il grafico
Minimum k|k minimo
Maximum k|k massimo
Standardize|Standardizza
Criterion|Criterio
Gap simulations|Simulazioni gap
Gap statistic|Statistica Gap
Gap reference geometry|Geometria del riferimento Gap
Variable ranges|Intervalli delle variabili
Principal component ranges|Intervalli delle componenti principali
Krzanowski–Lai scaling|Scala di Krzanowski–Lai
Clusters|Gruppi
Observation labels|Etichette delle osservazioni
Direction|Direzione
Scale columns|Scala colonne
Scale rows|Scala righe
Linkage|Criterio di collegamento
Distance|Distanza
Row cut|Taglio delle righe
Row cut height|Altezza di taglio delle righe
Column cut|Taglio delle colonne
Column clusters|Gruppi delle colonne
Column cut height|Altezza di taglio delle colonne
Graph output|Grafico da produrre
Dendrogram orientation|Orientamento del dendrogramma
Hierarchy axis|Asse del raggruppamento gerarchico
All fitted axes|Tutti gli assi calcolati
Branch appearance|Aspetto dei rami
Branch width|Spessore dei rami
Branch style|Stile dei rami
Branch opacity (%)|Opacità dei rami (%)
Label type|Tipo di etichetta
First label|Prima etichetta
Label interval (0 = automatic)|Intervallo delle etichette (0 = automatico)
Label angle|Angolo delle etichette
Show cut line|Mostra linea di taglio
Scaled data|Dati scalati
Distance matrix|Matrice delle distanze
Merge map|Mappa delle fusioni
Elbow data|Dati del grafico a gomito
Elbow plot|Grafico a gomito
Silhouette data|Dati della silhouette
Silhouette plot|Grafico della silhouette
Clustered data plot|Grafico dei dati per gruppo
Define clusters by count or height to plot clustered data.|Definisci i gruppi per numero o altezza per mostrare il grafico dei dati.
Choose an axis with clusters defined by count or height.|Scegli una direzione con gruppi definiti per numero o altezza.
Gap data|Dati della statistica Gap
Gap plot|Grafico della statistica Gap
Gap reference datasets|Campioni di riferimento per Gap
Gap seed|Seme casuale per Gap
Choose between 5 and 100 Gap reference datasets.|Scegli da 5 a 100 campioni di riferimento per Gap.
Gap seed must be an integer between 0 and 4294967295.|Il seme casuale per Gap deve essere un intero da 0 a 4294967295.
The chosen distance is undefined for the simulated Gap data.|La distanza scelta non è definita per i dati simulati della statistica Gap.
The reference linkage produced non-finite merge distances.|Il metodo di collegamento ha prodotto distanze di fusione non finite nei campioni di riferimento.
Cophenetic distances|Distanze cofenetiche
Cophenetic correlation|Correlazione cofenetica
Matrix format|Formato della matrice
Ellipse grouping|Raggruppamento dell’ellisse
Ellipse group|Gruppo dell’ellisse
Level (%)|Livello (%)
Center marker|Simbolo del centro
Center size|Dimensione del centro
Fill|Riempimento
Fill color|Colore di riempimento
Fill opacity (%)|Opacità del riempimento (%)
Border|Bordo
Border color|Colore del bordo
Border width|Spessore del bordo
Border opacity (%)|Opacità del bordo (%)
Border style|Stile del bordo
Center|Centro
Interval|Intervallo
Overlay observations|Sovrapponi osservazioni
Point placement|Disposizione dei punti
X categories|Categorie X
Y categories|Categorie Y
Cell value|Valore della cella
Transpose|Trasponi
Reverse rows|Inverti righe
Reverse columns|Inverti colonne
Cell shape|Forma delle celle
Cell borders|Bordi delle celle
Mark missing cells|Segnala celle mancanti
Show cell values|Mostra valori delle celle
Palette|Tavolozza
Color scale|Scala dei colori
Color minimum (blank = automatic)|Colore minimo (vuoto = automatico)
Color midpoint (blank = automatic)|Colore intermedio (vuoto = automatico)
Color maximum (blank = automatic)|Colore massimo (vuoto = automatico)
Missing color|Colore dei valori mancanti
Out-of-range color (blank = clamp)|Colore fuori intervallo (vuoto = estremo della scala)
Single gradient|Gradiente singolo
Double gradient|Gradiente doppio
Minimum color|Colore del minimo
Midpoint color|Colore del punto centrale
Maximum color|Colore del massimo
Color opacity|Opacità dei colori
Category colors|Colori delle categorie
Show color legend|Mostra la legenda dei colori
Color legend orientation|Orientamento della legenda
Reverse color legend|Inverti la legenda dei colori
Color legend title|Titolo della legenda
Color legend interval|Intervallo dei tick della legenda
Color legend start|Primo tick della legenda
Colors|Colori
Categories|Categorie
Placement of groups|Disposizione dei gruppi
Summary error|Errore dei valori riassuntivi
SEM source|Origine dell’errore standard
Bins|Classi
Distribution|Distribuzione
Units|Unità
Bin width (blank = automatic)|Ampiezza delle classi (vuoto = automatica)
First bin center (blank = automatic)|Centro della prima classe (vuoto = automatico)
Maximum value (blank = no limit)|Valore massimo (vuoto = nessun limite)
Replicates|Repliche
Y scale|Scala Y
Style|Stile
Whiskers|Baffi
Show mean|Mostra media
Bandwidth multiplier|Moltiplicatore della larghezza di banda
Median line|Linea della mediana
Quartile lines|Linee dei quartili
Size|Dimensione
Label|Etichetta
Maximum area (pt²)|Area massima (pt²)
Show labels|Mostra etichette
Show size legend|Mostra legenda delle dimensioni
Pairs|Coppie
Orientation|Orientamento
Show unpaired observations|Mostra osservazioni non appaiate
Show group mean|Mostra media del gruppo
Estimate|Stima
Lower limit|Limite inferiore
Upper limit|Limite superiore
Weight|Peso
Study columns|Colonne degli studi
Estimate row|Riga delle stime
Lower row|Riga dei limiti inferiori
Upper row|Riga dei limiti superiori
Measure|Misura
Scale|Scala
Reference|Riferimento
Show reference|Mostra riferimento
Interval level (%)|Livello dell’intervallo (%)
X source|Origine dei valori X
X column|Colonna X
Mean A|Media A
Mean B|Media B
SD A|Deviazione standard A
SD B|Deviazione standard B
Probability A|Probabilità A
Probability B|Probabilità B
X minimum|X minimo
X maximum|X massimo
Intercept|Intercetta
Slope|Pendenza
SD|Deviazione standard
Null value|Valore sotto l’ipotesi nulla
First row|Prima riga
Last row|Ultima riga
Y sets|Serie Y
Row title|Titolo della riga
X transform|Trasformazione X
Y transform|Trasformazione Y
Order|Ordine
Plot|Grafico
Output table|Tabella risultante
Include variable name prefixes|Includi prefissi con i nomi delle variabili
Only include complete rows|Includi solo righe complete
Independent (X) variable|Variabile indipendente (X)
Response variable|Variabile di risposta
Grouping variable|Variabile di raggruppamento
Subject/replicate variable|Variabile soggetto/replica
Row factor variable|Variabile del fattore di riga
Column factor variable|Variabile del fattore di colonna
Row (treatment) variable|Variabile di riga (trattamento)
Column (outcome) variable|Variabile di colonna (esito)
Count variable|Variabile dei conteggi
Choose XY, Column, Grouped or Contingency.|Scegli XY, Colonna, Raggruppata o Contingenza.
Each source variable must have a unique name.|Ogni variabile di origine deve avere un nome univoco.
Within factors|Fattori entro soggetto
Between factors|Fattori tra soggetti
Measurement columns|Colonne delle misure
Repeat across|Ripeti tra
Subject IDs|Identificativi dei soggetti
Comparison factor|Fattore di confronto
Condition on factors|Condiziona sui fattori
Comparison families|Famiglie di confronti
Series|Serie
X values|Valori X
Merge numbered replicates|Unisci repliche numerate
Choose numbered replicates or grouping variables.|Scegli le repliche numerate oppure le variabili di raggruppamento.
Select up to eight response series.|Seleziona fino a otto serie di risposta.
Parameter intervals|Intervalli dei parametri
Compare with independent fits|Confronta con adattamenti indipendenti
Show confidence bands|Mostra bande di confidenza
Replace zero X|Sostituisci X uguale a zero
Zero replacement (original units)|Valore sostitutivo dello zero (unità originali)
Change units|Cambia unità
Unit factor|Fattore di conversione
Logarithm|Logaritmo
Data columns|Colonne dei dati
Baseline column|Colonna di riferimento
Baseline subcolumns|Sottocolonne di riferimento
Replicate handling|Gestione delle repliche
Baseline|Riferimento
Rows for baseline (K)|Righe per il riferimento (K)
Drop baseline rows|Elimina righe di riferimento
Operation|Operazione
X minimum (blank = no limit)|X minimo (vuoto = nessun limite)
X maximum (blank = no limit)|X massimo (vuoto = nessun limite)
Rows per group (K)|Righe per gruppo (K)
Average only rows above an X threshold|Media solo delle righe oltre una soglia X
X threshold|Soglia X
Divide by|Dividi per
Show as|Mostra come
Confidence interval|Intervallo di confidenza
Comparison family|Famiglia di confronti
Sphericity correction|Correzione della sfericità
Huynh-Feldt|Huynh–Feldt
Lower bound|Limite inferiore
Control|Controllo
Patient|Paziente
Control A|Controllo A
Control B|Controllo B
Patient A|Paziente A
Patient B|Paziente B
Direction A|Direzione A
Direction B|Direzione B
Agreement coverage (%)|Copertura di concordanza (%)
Confidence intervals for agreement limits|Intervalli di confidenza dei limiti di concordanza
Y / X error variance|Varianza dell’errore Y / X
Identity line|Retta di identità
Peaks|Picchi
Minimum height (%)|Altezza minima (%)
Minimum width|Larghezza minima
Unknown responses|Risposte incognite
Only rows without X|Solo righe senza X
Unknown X|X incognite
Replicate count column|Colonna del numero di repliche
Duplicate X|X duplicate
Interior knots|Nodi interni
LOWESS fraction|Frazione LOWESS
Robust iterations|Iterazioni robuste
Query|Valori da stimare
Segments|Segmenti
Residuals|Residui
First derivative|Derivata prima
Second derivative|Derivata seconda
Integral|Integrale
Predictors|Predittori
Categorical predictors|Predittori categorici
Family|Famiglia
Exposure|Esposizione
Diagnostics|Diagnostica
Residual plot|Grafico dei residui
Weight exponent K|Esponente dei pesi K
Event|Evento
Ties|Valori a pari merito
Event value|Valore dell’evento
Censor value|Valore di censura
Predict survival|Stima sopravvivenza
Profiles|Profili
Cox diagnostics|Diagnostica di Cox
Schoenfeld residuals|Residui di Schoenfeld
Schoenfeld term|Termine di Schoenfeld
Scaled Schoenfeld residuals|Residui di Schoenfeld scalati
Cox-Snell diagnostics|Diagnostica Cox–Snell
Schoenfeld x axis|Asse X di Schoenfeld
Event time|Tempo dell’evento
Source row|Riga di origine
Goal|Obiettivo
Standardized effect|Effetto standardizzato
Target power|Potenza desiderata
N (per group, if independent)|N (per gruppo, se indipendenti)
ANOVA groups|Gruppi ANOVA
Mean|Media
Success probability A|Probabilità di successo A
Success probability B|Probabilità di successo B
Paired|Appaiato
One-sample|Un campione
Two-sided|Bilaterale
Greater|Maggiore
Less|Minore
None|Nessuno
Automatic|Automatico
Discard|Scarta
All pairs|Tutte le coppie
Versus control|Rispetto al controllo
Selected pairs|Coppie selezionate
Uncorrected|Senza correzione
Positive|Positiva
Negative|Negativa
Pairwise complete|Casi completi per coppia
Listwise complete|Solo casi completi
Exact when feasible|Esatto se fattibile
Approximate|Approssimato
Raw replicates|Repliche grezze
Mean, SD and N|Media, deviazione standard e N
Mean, SEM and N|Media, errore standard e N
Welch t-test|Test t di Welch
Student t-test|Test t di Student
Paired t-test|Test t appaiato
Wilcoxon matched pairs|Wilcoxon per coppie appaiate
Volcano plot|Grafico a vulcano
Differences and intervals|Differenze e intervalli
Legacy|Metodo precedente
Unadjusted|Senza correzione
Observations|Osservazioni
Count matrix|Matrice dei conteggi
Require counts|Richiedi conteggi
Treat blanks as zero|Considera le celle vuote come zero
Pearson chi-square|Chi quadrato di Pearson
Fisher exact (2 × 2)|Test esatto di Fisher (2 × 2)
Fisher exact (R × C)|Test esatto di Fisher (R × C)
Yates-corrected chi-square|Chi quadrato con correzione di Yates
Fisher Monte Carlo|Fisher con simulazione Monte Carlo
Cochran–Armitage trend|Test di tendenza di Cochran–Armitage
First row odds higher|Odds maggiori nella prima riga
First row odds lower|Odds minori nella prima riga
Donut|Ciambella
Pie|Torta
Horizontal slices|Settori orizzontali
Vertical slices|Settori verticali
Dot plot|Grafico a punti
Category and percent|Categoria e percentuale
Category and value|Categoria e valore
Category only|Solo categoria
Percent|Percentuale
Equal proportions|Proporzioni uguali
Weights in a column|Pesi in una colonna
Expected counts in a column|Conteggi attesi in una colonna
Confidence (mean)|Confidenza (media)
Prediction (new observation)|Previsione (nuova osservazione)
Fit|Adattamento
Residuals vs fitted|Residui rispetto ai valori stimati
Long table|Tabella lunga
Wide XY|XY in formato largo
Individual lines|Rette individuali
Model chosen by the comparison|Modello scelto dal confronto
Filled|Riempita
Lines|Linee
Separate|Separati
Pooled|Combinati
Homoscedasticity|Omoschedasticità
Normal Q–Q|Q–Q normale
Report an error|Segnala un errore
Treat as missing|Considera come mancante
Survival|Sopravvivenza
Cumulative events|Eventi cumulativi
Fraction|Frazione
Censored observations|Osservazioni censurate
All observations|Tutte le osservazioni
Final censor only|Solo censura finale
Standard error bars|Barre dell’errore standard
Pointwise confidence band|Banda di confidenza puntuale
Pointwise confidence bars|Barre di confidenza puntuali
Hall–Wellner simultaneous band|Banda simultanea Hall–Wellner (conservativa)
Symmetric Greenwood|Greenwood simmetrico
Rows and columns|Righe e colonne
Count|Conteggio
Cut height|Altezza di taglio
No cut|Nessun taglio
Vertical|Verticale
Horizontal|Orizzontale
By cluster|Per gruppo
Single color|Colore unico
Solid|Continua
Dashed|Tratteggiata
Dotted|Punteggiata
Numbers|Numeri
Letters|Lettere
Full|Completa
Lower triangle|Triangolo inferiore
Confidence region of mean|Regione di confidenza della media
Data ellipse|Ellisse dei dati
Convex hull|Inviluppo convesso
Match point groups|Come i gruppi dei punti
All XY data|Tutti i dati XY
Separate categorical variable|Variabile categorica separata
Circle|Cerchio
Square|Quadrato
Diamond|Rombo
Triangle up|Triangolo verso l’alto
Triangle down|Triangolo verso il basso
Plus|Più
Cross|Croce
Star|Stella
By group|Per gruppo
Dash-dot|Tratto-punto
Individual points|Punti individuali
Bars|Barre
Center and interval|Centro e intervallo
Floating range|Intervallo sospeso
Before and after|Prima e dopo
Median|Mediana
SEM|Errore standard
Range|Intervallo
Interquartile range|Intervallo interquartile
Spread exact ties|Separa i valori identici
Centered|Centrati
Jitter|Dispersione casuale
Matrix|Matrice
Long numeric|Formato lungo numerico
Long categories|Formato lungo categorico
Geometric mean|Media geometrica
Stretch|Allunga
Blues|Blu
Blue–red|Blu–rosso
Greys|Grigi
Linear|Lineare
Diverging|Divergente
Precomputed summaries|Valori riassuntivi precalcolati
Interleaved|Affiancati
Superimposed|Sovrapposti
Stacked|Impilati
100% stacked|Impilati al 100%
Distances from estimate (minus/plus)|Distanze dalla stima (meno/più)
Limits on axis (lower/upper)|Limiti sull’asse (inferiore/superiore)
Distances|Distanze
Endpoints|Estremi
Both|Entrambe
Negative only|Solo negativa
Positive only|Solo positiva
solid|continua
dashed|tratteggiata
dotted|punteggiata
dash-dot|tratto-punto
Binned frequency|Frequenza per classi
Binned cumulative|Cumulativa per classi
Exact cumulative|Cumulativa esatta
Counts|Conteggi
Fractions|Frazioni
Percentages|Percentuali
Separate variables|Variabili separate
Pool within each series|Combina entro ogni serie
Mean by worksheet row|Media per riga del foglio
Default|Predefinito
XY points|Punti XY
XY spikes|Linee verticali XY
Gaussian probability|Probabilità normale
Single response|Risposta singola
Separate columns|Colonne separate
Box|Scatola
Violin|Violino
Min to max|Da minimo a massimo
Min to max with all observations|Da minimo a massimo con tutte le osservazioni
Replicate subcolumns|Sottocolonne delle repliche
Line|Linea
Line and points|Linea e punti
One study per row|Uno studio per riga
One study per column|Uno studio per colonna
Ratio|Rapporto
Difference|Differenza
Iterative Grubbs|Grubbs iterativo
Welch difference|Differenza di Welch
OLS slope|Pendenza dei minimi quadrati
Estimates|Stime
P values|Valori p
Generated|Generati
Reciprocal|Reciproco
Source order|Ordine originale
Ascending X within each set|X crescenti in ogni serie
Column|Colonna
Grouped|Raggruppata
Contingency|Contingenza
Wide repeated measures|Misure ripetute in formato largo
Grouped replicate table|Tabella raggruppata delle repliche
Columns only|Solo colonne
Rows only|Solo righe
Unique across groups|Univoci tra tutti i gruppi
Restart within between groups|Riparti per ciascun gruppo tra soggetti
As entered|Come inseriti
Log10 concentrations|Log10 delle concentrazioni
Individual observations|Osservazioni individuali
Means at each X|Medie per ogni X
Symmetric t|t simmetrico
Profile likelihood|Verosimiglianza profilata
Show estimation plot|Mostra grafico della stima
Plot paired differences|Grafico delle differenze appaiate
Plot paired correlation|Grafico di correlazione delle coppie
Matched observations|Osservazioni appaiate
Differences|Differenze
Mean and 95% CI|Media e IC 95%
Paired effect|Effetto appaiato
Report log10(IC50)|Mostra log10(IC50)
No change|Nessuna modifica
Multiply by|Moltiplica per
Natural log|Logaritmo naturale
Independent columns|Colonne indipendenti
Each replicate vs baseline mean|Ogni replica rispetto alla media di riferimento
Mean vs baseline mean|Media rispetto alla media di riferimento
Matched subcolumns|Sottocolonne appaiate
Baseline column, same row|Colonna di riferimento, stessa riga
Mean of first K rows|Media delle prime K righe
Mean of last K rows|Media delle ultime K righe
Linear fit of baseline column vs X|Retta della colonna di riferimento rispetto a X
Difference: Y − baseline|Differenza: Y − riferimento
Ratio: Y / baseline|Rapporto: Y / riferimento
Sum: Y + baseline|Somma: Y + riferimento
Product: Y × baseline|Prodotto: Y × riferimento
Keep rows within an X range|Mantieni righe entro un intervallo X
Average every K rows (sorted by X)|Media ogni K righe (ordinate per X)
Column total|Totale della colonna
Row total|Totale della riga
Grand total|Totale generale
All three (separate tables)|Tutti e tre (tabelle separate)
All three (one table)|Tutti e tre (unica tabella)
Ordinary|Ordinaria
Welch and Brown–Forsythe|Welch e Brown–Forsythe
Higher in patients|Maggiore nei pazienti
Lower in patients|Minore nei pazienti
Percent difference|Differenza percentuale
Log ratio (geometric)|Logaritmo del rapporto (geometrico)
Off|Disattivato
Above baseline|Sopra il riferimento
Above and below|Sopra e sotto
X from Y|X da Y
Y from X|Y da X
Nonlinear|Non lineare
Asymmetric dose-response (concentration X)|Dose-risposta asimmetrica 5PL (concentrazione X)
Asymmetric dose-response (log10 X)|Dose-risposta asimmetrica 5PL (log10 X)
Two-phase decay with fixed K2|Decadimento a due fasi con K2 fissato
Linear-quadratic cell survival|Sopravvivenza cellulare lineare-quadratica (frazione)
Linear-quadratic cell survival (percent)|Sopravvivenza cellulare lineare-quadratica (percentuale)
Linear-quadratic cell survival (counts)|Sopravvivenza cellulare lineare-quadratica (conteggio)
Linear-quadratic fractional cell death|Morte cellulare lineare-quadratica (frazione)
Linear-quadratic cell death (percent)|Morte cellulare lineare-quadratica (percentuale)
Linear-quadratic cell death (counts)|Morte cellulare lineare-quadratica (conteggio)
Operational model (full and partial) (concentration X)|Modello operativo per agonisti pieni e parziali (concentrazione X)
Operational model (full and partial) (log10 X)|Modello operativo per agonisti pieni e parziali (log10 X)
Mean response|Risposta media
Prediction|Previsione
Point-to-point|Da punto a punto
Cubic spline|Spline cubica
Akima spline|Spline di Akima
Smoothing spline|Spline di smussamento
Reject|Rifiuta
Average|Media
Differentiate|Deriva
Cumulative integral|Integrale cumulativo
Curve pipeline|Pipeline della curva
Identity|Identità
First difference|Differenza prima
Second difference|Differenza seconda
Cumulative trapezoid|Integrale cumulato (trapezi)
Smoothing|Smussamento
Savitzky–Golay|Savitzky–Golay
Initial integral|Integrale iniziale
Half-window|Semilarghezza
Polynomial degree|Grado del polinomio
Geometric|Geometrico
Confidence|Confidenza
Scores|Punteggi
Loadings|Coefficienti delle componenti
Scree|Grafico degli autovalori
Proportion of variance|Proporzione di varianza
All|Tutte
Logistic|Logistica
Gaussian|Normale
Absolute residuals vs fitted|Residui assoluti rispetto ai valori stimati
Observed vs fitted|Osservati rispetto ai valori stimati
Predicted survival|Sopravvivenza stimata
Deviance vs linear predictor|Devianza rispetto al predittore lineare
Schoenfeld vs time|Schoenfeld rispetto al tempo
Scaled Schoenfeld|Schoenfeld scalati
Cox-Snell plot|Grafico Cox–Snell
Percent of range|Percentuale dell’intervallo
Z score|Punteggio Z
Percent of first value|Percentuale del primo valore
Subtract first value|Sottrai primo valore
Square root|Radice quadrata
Absolute value|Valore assoluto
Sample size|Dimensione del campione
Power|Potenza
One-sample t|Test t a un campione
Paired t|Test t appaiato
Independent t|Test t indipendente
Normal|Normale
XY with normal noise|XY con rumore normale
2 × 2 contingency|Contingenza 2 × 2
Previous rows|Righe precedenti
Next rows|Righe successive
Before|Prima
After|Dopo
Title (optional)|Titolo (facoltativo)
Recalculate panels|Ricalcola pannelli
Calculate this analysis using the current data.|Calcola questa analisi con i dati attuali.
Recalculate|Ricalcola
Open saved view|Apri vista salvata
Change Parameters…|Modifica parametri…
Use Result as Data|Usa risultato come dati
Edit panel…|Modifica pannello…
Graph settings…|Impostazioni del grafico…
Confidence overlays…|Regioni di confidenza…
Pairwise comparisons…|Confronti a coppie…
View original|Mostra originale
Open editable graph|Apri grafico modificabile
Edit graph data|Modifica dati del grafico
Saved controls|Controlli salvati
Absolute IC50|IC50 assoluta
Relative IC50|IC50 relativa
Format…|Formato…
Edit panel data…|Modifica dati del pannello…
New column|Nuova colonna
Column name|Nome della colonna
Calculated column|Colonna calcolata
New or existing calculated column name|Nome della colonna calcolata nuova o esistente
Paste Special|Incolla speciale
Filter rows|Filtra righe
Rows to skip|Righe da saltare
Keep the first selected row, then skip the specified number between rows.|Mantieni la prima riga selezionata, poi salta il numero indicato di righe tra una riga e l’altra.
Check the row filter|Controlla il filtro delle righe
Enter whole numbers for the row range and rows to skip.|Inserisci numeri interi per l’intervallo di righe e per le righe da saltare.
Edit imported layout panel|Modifica pannello del layout importato
Panel|Pannello
Left|Sinistra
Top|Alto
Width|Larghezza
Height|Altezza
Restore original position|Ripristina posizione originale
Check panel|Controlla il pannello
Enter whole numbers for the position and size.|Inserisci numeri interi per posizione e dimensioni.
Enter whole-number coordinates for the panel.|Inserisci coordinate intere per il pannello.
Enter a positive panel width and height within the layout.|Inserisci larghezza e altezza positive entro il layout.
Keep the panel within the original layout’s panel area.|Mantieni il pannello entro l’area dei pannelli del layout originale.
Invalid legacy layout edits.|Le modifiche al layout importato non sono valide.
Reuse seed|Riutilizza seme
New seed|Nuovo seme
Copy seed|Copia seme
The groups changed. Review the order.|I gruppi sono cambiati. Controlla l’ordine.
Remove unavailable pairs and choose groups in the current data.|Rimuovi le coppie non disponibili e scegli i gruppi presenti nei dati attuali.
Choose two different groups.|Scegli due gruppi diversi.
This pair is already in the list.|Questa coppia è già nell’elenco.
Remove unavailable pairs and choose columns in the current data.|Rimuovi le coppie non disponibili e scegli le colonne presenti nei dati attuali.
Choose two different columns for Before and After.|Scegli due colonne diverse per Prima e Dopo.
Use the same codes for all selected status columns. Text matches as written.|Usa gli stessi codici per tutte le colonne di stato selezionate. Il testo deve corrispondere esattamente.
"""

CAPTIONS = dict(line.split("|", 1) for line in _TEXT.strip().splitlines())

# Deming regression (0.93). Canonical recipes stay English; these captions are display text.
CAPTIONS.update({
    "Uncertainty input": "Specifica dell’incertezza",
    "Known SDs": "SD note",
    "X error SD": "SD dell’errore X",
    "Y error SD": "SD dell’errore Y",
    "Y series": "Serie Y",
    "Show projections": "Mostra le proiezioni",
    "Compare paired series": "Confronta le serie appaiate",
})

CAPTIONS.update({
    "Geometric mean": "Media geometrica",
    "Geometric mean and 95% CI": "Media geometrica e IC al 95%",
    "Geometric mean requires strictly positive observations.": "La media geometrica richiede osservazioni strettamente positive.",
    "For a geometric mean, choose a confidence interval or no interval.": "Per la media geometrica, scegli un intervallo di confidenza o nessun intervallo.",
    "Summary format": "Tipo di riepilogo", "Full summary": "Riepilogo completo",
    "Geometric summary": "Riepilogo geometrico", "Include sum": "Includi la somma",
    "Shapiro–Wilk": "Shapiro–Wilk", "D’Agostino–Pearson": "D’Agostino–Pearson",
    "Anderson–Darling": "Anderson–Darling", "Kolmogorov–Smirnov (Lilliefors)": "Kolmogorov–Smirnov (Lilliefors)",
    "Alpha": "Alfa", "Q–Q plot": "Grafico Q–Q", "Q–Q variable": "Variabile Q–Q",
    "Q–Q reference line": "Retta di riferimento Q–Q", "Kruskal–Wallis p value": "Valore p di Kruskal–Wallis",
    "Dunn comparisons": "Confronti di Dunn", "Control group": "Gruppo di controllo",
    "Dunn adjustment": "Correzione di Dunn", "Dunn alpha": "Alfa di Dunn",
    "Spearman p values": "Valori p di Spearman", "Donut hole (%)": "Foro della ciambella (%)",
    "Detailed results": "Risultati dettagliati", "Confidence level (%)": "Livello di confidenza (%)",
    "P adjustment": "Correzione dei p", "Show intervals": "Mostra gli intervalli",
    "Exact": "Esatto", "Holm": "Holm", "Benjamini–Hochberg": "Benjamini–Hochberg",
    "Correlate against control": "Correla con un controllo",
    "Compare independent correlations": "Confronta correlazioni indipendenti",
    "Repeated-measures correlation": "Correlazione a misure ripetute",
    "Subject bootstrap": "Bootstrap per soggetti", "Bootstrap replicates": "Repliche bootstrap",
    "Number of dots": "Numero di punti", "Start angle": "Angolo iniziale", "Clockwise": "Senso orario",
    "Slice labels": "Etichette dei settori", "Control level(s), separated by |": "Livelli di controllo, separati da |",
    "Gehan–Breslow–Wilcoxon": "Gehan–Breslow–Wilcoxon", "X error distance": "Distanza dell’errore X",
    "Error cap size": "Dimensione delle estremità delle barre", "Error width": "Spessore delle barre di errore",
    "Q (%)": "Q (%)", "N A": "N A", "N B": "N B", "N": "N",
    "Diagnostics and predictions": "Diagnostica e previsioni",
    "Linear diagnostics": "Diagnostica lineare", "Linear residual plot": "Grafico dei residui lineari",
    "Linear profiles": "Profili lineari", "Linear CI (%)": "IC lineare (%)", "p value": "Valore p",
    "Exact permutation": "Permutazione esatta", "Chi-square approximation": "Approssimazione chi quadrato",
    "Conditional exact": "Esatto condizionato", "Baptista–Pike exact": "Esatto di Baptista–Pike",
    "Koopman score": "Punteggio di Koopman", "Wilson (no continuity correction)": "Wilson (senza correzione di continuità)",
    "Clopper–Pearson (exact)": "Clopper–Pearson (esatto)",
    "Wilson–Brown (modified Wilson)": "Wilson–Brown (Wilson modificato)",
    "First time with S ≤ 0.5": "Primo tempo con S ≤ 0,5",
    "Midpoint of recorded 50% plateau": "Punto medio del tratto registrato al 50%",
    "Elbow": "Gomito", "Consensus (17 indices)": "Consenso (17 indici)",
    "Dimension-adjusted": "Corretto per la dimensione", "Unscaled WSS": "WSS senza riscalatura",
    "average": "media", "complete": "completo", "single": "singolo", "weighted": "ponderato",
    "centroid": "centroide", "median": "mediana", "euclidean": "euclidea", "cityblock": "Manhattan",
    "cosine": "coseno", "correlation": "correlazione", "Dendrogram": "Dendrogramma",
    "Entered SEM, else SD / √N": "Errore standard inserito, altrimenti DS / √N",
    "Pearson 2x2": "Pearson 2 × 2",
    "Alternate columns: A, C, E… are baselines": "Colonne alternate: A, C, E… sono riferimenti",
    "Alternate columns: B, D, F… are baselines": "Colonne alternate: B, D, F… sono riferimenti",
    "Fractional difference: (Y − baseline) / baseline": "Differenza relativa: (Y − riferimento) / riferimento",
    "Percent difference: 100 × (Y − baseline) / baseline": "Differenza percentuale: 100 × (Y − riferimento) / riferimento",
    "Geisser–Greenhouse (one-way)": "Geisser–Greenhouse (una via)",
    "Unavailable pair": "Coppia non disponibile",
    "Graph style applied.": "Stile del grafico applicato.",
    "Selected cell values copied.": "Valori delle celle selezionate copiati.",
    "Data updated.": "Dati aggiornati.",
    "Wait for the current calculation before switching projects.": "Attendi la fine del calcolo prima di cambiare progetto.",
    "Layout could not be updated.": "Impossibile aggiornare il layout.",
    "Pairwise comparisons unchanged.": "Confronti a coppie invariati.",
    "Analysis could not be completed.": "Impossibile completare l’analisi.",
    "Cancelling after the current block of replicates…": "Annullamento al termine del blocco attuale di repliche…",
    "Project Info": "Informazioni sul progetto",
    "Coordinates use the original layout units.\nApply one panel at a time.":
        "Le coordinate usano le unità del layout originale.\nApplica un pannello alla volta.",
})

# Formatted sentences use named placeholders so data supplied by users stays literal.
MESSAGES = {
    "interface.rows_position": ("Rows {first}–{last} of {total}", "Righe {first}–{last} di {total}"),
    "interface.paste_into": ("Paste into {address}", "Incolla in {address}"),
    "interface.clipboard_size": ("Clipboard  ·  {rows} rows × {columns} columns", "Appunti  ·  {rows} righe × {columns} colonne"),
    "interface.max_pairs": ("Plot up to {count} pairs at once.", "Traccia fino a {count} coppie alla volta."),
    "interface.linked_to": ("Linked to {table}", "Collegato a {table}"),
    "interface.layout_panels": ("Layout  ·  {count} panels", "Layout  ·  {count} pannelli"),
    "interface.running": ("Running {method}…", "Analisi in corso: {method}…"),
    "interface.progress": ("Running {method}… {done} of {total} replicates", "Analisi in corso: {method}… {done} di {total} repliche"),
    "interface.updating": ("Updating {name}…", "Aggiornamento di {name}…"),
    "interface.updated": ("{name} updated.", "{name} aggiornato."),
    "interface.exported": ("Exported {name}.", "Esportato {name}."),
}

CAPTIONS.update({
    "Use Format Graph for an imported XY graph, or Export for its original preview.":
        "Usa Formato grafico per un grafico XY importato oppure Esporta per l’anteprima originale.",
    "Edited imported vector image": "Immagine vettoriale importata modificata",
    "Original imported vector image": "Immagine vettoriale importata originale",
})

# Normalize to references. Keys already used by other commands (Input, Mean, SD, None, …) stay as they are.
CAPTIONS.update({
    "Normalize to references": "Normalizza sui riferimenti",
    "Raw values": "Valori grezzi",
    "Summary values": "Valori riassuntivi",
    "Normalize row means": "Normalizza le medie di riga",
    "Each replicate, common references": "Ogni replica, riferimenti comuni",
    "First-last lower": "Primo-ultimo, il più basso",
    "First-last higher": "Primo-ultimo, il più alto",
    "Constant": "Costante",
    "Selected rows mean": "Media delle righe scelte",
    "Sum": "Somma",
    "Minimum": "Minimo",
    "Maximum": "Massimo",
    "Keep": "Mantieni",
    "Blank reference values": "Nascondi i valori di riferimento",
    "Limits": "Limiti",
    "Allow reversed references": "Consenti riferimenti invertiti",
    "Reference values in output": "Valori di riferimento nel risultato",
    "Graph results": "Grafico dei risultati",
    "Error format": "Formato dell’errore",
    "Error lower": "Errore inferiore",
    "Error upper": "Errore superiore",
    "Zero reference": "Riferimento zero",
    "One reference": "Riferimento uno",
    "Zero value": "Valore zero",
    "One value": "Valore uno",
    "Zero rows": "Righe dello zero",
    "One rows": "Righe dell’uno",
    "References": "Riferimenti",
    "Spearman exact budget": "Risorse per Spearman esatto",
    "Extended (17 pairs)": "Esteso (17 coppie)",
    "Standard (9 pairs)": "Standard (9 coppie)",
    "Cancelling calculation…": "Annullamento del calcolo…",
})

CAPTIONS.update({
    "Spearman exact budget": "Risorse per Spearman esatto",
    "Extended (17 pairs)": "Esteso (17 coppie)",
    "Standard (9 pairs)": "Standard (9 coppie)",
    "Cancelling calculation…": "Annullamento del calcolo…",
})

CAPTIONS.update({
    "Lognormal": "Lognormale",
    "Compare distributions": "Confronta le distribuzioni",
    "Choose Normal, Lognormal or Both.": "Scegli Normale, Lognormale o Entrambe.",
    "Lognormal Q–Q requires strictly positive values in the selected variable.":
        "Il grafico Q–Q lognormale richiede valori strettamente positivi nella variabile scelta.",
})

CAPTIONS.update({
    "One-way ANOVA from summaries": "ANOVA a una via da riepiloghi",
    "Groups in rows": "Gruppi nelle righe",
    "Summary subcolumns": "Sottocolonne di riepilogo",
    "Dispersion": "Dispersione",
    "Sample size": "Numerosità campionaria",
    "Dispersion type": "Tipo di dispersione",
    "Summary row": "Riga dei riepiloghi",
    "Summary values must be finite numbers.": "I valori di riepilogo devono essere numeri finiti.",
    "Choose groups in rows or summary subcolumns.": "Scegli gruppi nelle righe o sottocolonne di riepilogo.",
    "Choose SD, SEM or CV (%).": "Scegli SD, SEM o CV (%).",
    "Choose None, Tukey, Holm or Bonferroni.": "Scegli Nessuno, Tukey, Holm o Bonferroni.",
    "Confidence level (%) must be between 0 and 100.": "Il livello di confidenza (%) deve essere tra 0 e 100.",
    "Choose an existing summary column.": "Scegli una colonna di riepilogo esistente.",
    "Summary roles must use distinct columns.": "I ruoli di riepilogo devono usare colonne distinte.",
    "Select the Mean, dispersion and N subcolumns for each group.":
        "Seleziona le sottocolonne Media, dispersione e N per ogni gruppo.",
    "Choose an existing worksheet row (starting at 1).": "Scegli una riga esistente del foglio (a partire da 1).",
    "Select only named Mean, SD, SEM, CV or N subcolumns.":
        "Seleziona solo sottocolonne con suffisso Mean, SD, SEM, CV o N.",
    "Each group must have unique summary roles.": "Ogni gruppo deve avere ruoli di riepilogo univoci.",
    "Each selected group needs Mean, the chosen dispersion and N.":
        "Ogni gruppo selezionato richiede Mean, la dispersione scelta e N.",
    "Each sample size must be an integer from 2 to 2^53.": "Ogni numerosità deve essere un intero da 2 a 2^53.",
    "Dispersion must be nonnegative.": "La dispersione non può essere negativa.",
    "CV (%) cannot define dispersion for a zero mean.": "CV (%) non può definire la dispersione con media zero.",
    "The SD conversion is outside the supported numeric range.":
        "La conversione in SD è fuori dall’intervallo numerico supportato.",
    "Provide between 2 and 30 complete groups.": "Fornisci da 2 a 30 gruppi completi.",
    "The total sample size must not exceed 2^53.": "La numerosità totale non deve superare 2^53.",
    "ANOVA requires positive pooled residual variance.": "L’ANOVA richiede una varianza residua aggregata positiva.",
    "The ANOVA statistic is outside the supported numeric range.":
        "La statistica ANOVA è fuori dall’intervallo numerico supportato.",
    "The confidence level is too close to a numerical boundary.":
        "Il livello di confidenza è troppo vicino a un limite numerico.",
    "Ordinary": "Ordinaria",
    "Welch and Brown–Forsythe": "Welch e Brown–Forsythe",
    "Games–Howell": "Games–Howell",
    "Tamhane T2": "Tamhane T2",
    "Choose Ordinary, Welch, or Welch and Brown–Forsythe.":
        "Scegli Ordinaria, Welch o Welch e Brown–Forsythe.",
    "Choose None, Games–Howell, Tamhane T2, Holm or Bonferroni.":
        "Scegli Nessuno, Games–Howell, Tamhane T2, Holm o Bonferroni.",
    "Tukey assumes equal variances. Choose None, Games–Howell, Tamhane T2, Holm or Bonferroni.":
        "Tukey assume varianze uguali. Scegli Nessuno, Games–Howell, Tamhane T2, Holm o Bonferroni.",
    "Games–Howell or Tamhane T2 requires the Welch or Welch and Brown–Forsythe method.":
        "Games–Howell o Tamhane T2 richiede il metodo Welch oppure Welch e Brown–Forsythe.",
    "Every group used by Welch ANOVA needs a positive SD.":
        "Ogni gruppo usato dall’ANOVA di Welch deve avere una SD positiva.",
    "The group means and SDs cannot be scaled into the range Welch ANOVA can represent.":
        "Medie e SD dei gruppi non possono essere scalate nell’intervallo rappresentabile dall’ANOVA di Welch.",
    "These summaries are treated as independent groups. They cannot reconstruct "
    "paired dependence, normality, residuals or the data distribution.":
        "Questi riepiloghi sono trattati come gruppi indipendenti. Non permettono di ricostruire "
        "dipendenza appaiata, normalità, residui o la distribuzione dei dati.",
})

# Independent t tests from sufficient statistics. Canonical recipes remain English.
CAPTIONS.update({
    "Unpaired t-test from summaries": "Test t non appaiato da riepiloghi",
    "Null difference": "Differenza ipotizzata",
    "Null difference must be a number.": "La differenza ipotizzata deve essere un numero.",
    "Null difference must be finite.": "La differenza ipotizzata deve essere finita.",
    "Confidence level (%) must be a number.": "Il livello di confidenza (%) deve essere un numero.",
    "Confidence level (%) must be finite.": "Il livello di confidenza (%) deve essere finito.",
    "Summary row must be a whole number.": "La riga dei riepiloghi deve essere un numero intero.",
    "Summary row exceeds the supported integer range.": "La riga dei riepiloghi supera l’intervallo degli interi supportato.",
    "Choose Welch or Student for independent groups.": "Scegli Welch o Student per gruppi indipendenti.",
    "Provide exactly two complete independent groups.": "Fornisci esattamente due gruppi indipendenti completi.",
    "At least one group must have a positive SD for a t-test.": "Per il test t almeno un gruppo deve avere SD positiva.",
    "The standard error is outside the supported numeric range.": "L’errore standard è fuori dall’intervallo numerico supportato.",
    "The t statistic is outside the supported numeric range.": "La statistica t è fuori dall’intervallo numerico supportato.",
    "Two-sided test; first complete group minus second. Groups must be independent. Summary data cannot assess pairing, normality or outliers.":
        "Test bilaterale: primo gruppo completo meno secondo. I gruppi devono essere indipendenti. I riepiloghi non consentono di valutare appaiamento, normalità o valori anomali.",
})

# False-discovery control. Canonical recipes stay English; these captions are display text.
CAPTIONS.update({
    "Control false discoveries": "Controllo delle false scoperte",
    "p columns": "Colonne dei valori p",
    "Family columns": "Colonne della famiglia",
    "Family scope": "Ambito della famiglia",
    "Each column separately": "Ogni colonna separatamente",
    "Pool selected columns": "Accorpa le colonne selezionate",
    "FDR method": "Metodo FDR",
    "Benjamini–Yekutieli": "Benjamini–Yekutieli",
    "Two-stage Benjamini–Krieger–Yekutieli": "Benjamini–Krieger–Yekutieli a due stadi",
    "Desired FDR (%)": "FDR desiderato (%)",
    "Show diagnostic plot": "Mostra il grafico diagnostico",
})

CAPTIONS.update({
    'Analyze result table…': 'Analizza tabella risultati…',
    'Source analysis': 'Analisi sorgente',
    'Change input result…': 'Cambia risultato di ingresso…',
})

CAPTIONS.update({
    "Ellipse group styles": "Stili delle ellissi per gruppo",
    "Edit group styles…": "Modifica stili per gruppo…",
    "Empty fields inherit the graph style.": "I campi vuoti ereditano lo stile del grafico.",
    "The grouping column has no observed values.": "La colonna dei gruppi non contiene valori osservati.",
    "Choose color…": "Scegli colore…",
    "Number": "Numero",
    "Border width must be between 0.1 and 72 points.": "Lo spessore del bordo deve essere tra 0,1 e 72 punti.",
    "Fill opacity (%) must be between 0 and 100.": "L’opacità del riempimento deve essere tra 0 e 100.",
    "Border opacity (%) must be between 0 and 100.": "L’opacità del bordo deve essere tra 0 e 100.",
})

# Compare independent ROC curves: the method, its fields and its fixed choices. Recipes keep the English values.
CAPTIONS.update({
    "Compare independent ROC curves": "Confronta curve ROC indipendenti",
    "Area and inference": "Area e inferenza",
    "Area": "Area",
    "Partial": "Parziale",
    "Standardized partial": "Parziale standardizzata",
    "Maximum FPR": "FPR massimo",
    "Inference": "Inferenza",
    "DeLong": "DeLong",
    "Percentile bootstrap": "Bootstrap percentile",
    "Bootstrap replicates": "Repliche bootstrap",
    "Bootstrap seed": "Seme del bootstrap",
    "Save bootstrap": "Salva le repliche bootstrap",
    "Calculation cancelled.": "Calcolo annullato.",
})

CAPTIONS.update({
    "ANCOVA": "ANCOVA (medie aggiustate)",
    "Covariate": "Covariata",
    "Slope model": "Modello delle pendenze",
    "Common": "Comune",
    "Reference X": "X di riferimento",
    "Reference domain": "Dominio del riferimento",
    "Common range": "Intervallo comune",
    "Against control": "Contro il controllo",
    "Adjustment": "Correzione",
    "Bonferroni": "Bonferroni",
    "Fitted lines": "Rette adattate",
    "Adjusted means": "Medie aggiustate",
})

# Grouped distribution plot: engine messages in the active language (placeholders keep worksheet text literal).
MESSAGES.update({
    "grouped.error.unique": ("Worksheet column names must be unique.", "I nomi delle colonne del foglio devono essere univoci."),
    "grouped.error.choose": ("Choose a column for {field}.", "Scegli una colonna per {field}."),
    "grouped.error.exists": ("Choose an existing column for {field}.", "Scegli una colonna esistente per {field}."),
    "grouped.error.category_same": ("Choose a category column different from the response.",
                                    "Scegli una colonna di categoria diversa dalla risposta."),
    "grouped.error.split_same": ("Choose a Split by column different from Response and Category.",
                                 "Scegli per «Dividi per» una colonna diversa da Risposta e Categoria."),
    "grouped.error.none": ("No row has a numeric Response together with every selected category.",
                           "Nessuna riga ha una Risposta numerica insieme a tutte le categorie scelte."),
    "grouped.error.points": ("Select fewer observations to draw this graph.",
                             "Seleziona meno osservazioni per disegnare questo grafico."),
    "grouped.error.density": ("Select fewer observations for the density estimate.",
                              "Seleziona meno osservazioni per la stima della densità."),
    "grouped.error.cells": ("Plot up to {limit} cells at once ({categories} categories × {series} series).",
                            "Traccia fino a {limit} celle alla volta ({categories} categorie × {series} serie)."),
    "grouped.error.text": ('Column "{name}" contains text or infinite values.',
                           'La colonna "{name}" contiene testo o valori infiniti.'),
    "grouped.error.complex": ('Column "{name}" contains complex data.', 'La colonna "{name}" contiene dati complessi.'),
    "grouped.error.precision": ('Column "{name}" contains integers outside the supported precision.',
                                'La colonna "{name}" contiene interi fuori dalla precisione supportata.'),
    "grouped.error.range": ("The selected values exceed the numeric range for this graph.",
                            "I valori scelti superano l'intervallo numerico di questo grafico."),
    "grouped.error.flag": ("{field}: choose on or off.", "{field}: scegli sì o no."),
    "grouped.error.choice": ("Choose a valid {field}.", "Scegli un valore valido per {field}."),
    "grouped.error.bandwidth_number": ("The bandwidth multiplier must be a number.",
                                       "Il moltiplicatore della larghezza di banda deve essere un numero."),
    "grouped.error.bandwidth_finite": ("The bandwidth multiplier must be finite and greater than zero.",
                                       "Il moltiplicatore della larghezza di banda deve essere finito e maggiore di zero."),
    "grouped.error.bandwidth_range": ("The bandwidth is outside the supported numeric range.",
                                      "La larghezza di banda è fuori dall'intervallo numerico supportato."),
    "grouped.error.density_range": ("The density is outside the supported numeric range.",
                                    "La densità è fuori dall'intervallo numerico supportato."),
    "grouped.error.number": ("{field} must be a number.", "{field} deve essere un numero."),
})

# K-means stability (0.96): the method, its fields and its engine messages. Recipes keep the English keys and
# values; the sheet titles and the worksheet text stay literal.
CAPTIONS.update({
    "K-means stability": "Stabilità K-means",
    "Resamples": "Ricampionamenti",
    "Sample fraction (%)": "Frazione campionata (%)",
    "Seed runs": "Ripetizioni con altri semi",
    "Report k": "k dei report per osservazione",
    "Show co-assignment matrix": "Mostra la matrice di co-assegnazione",
})

MESSAGES.update({
    "kstab.error.whole": ("{field}: enter a whole number from {low} to {high}.",
                          "{field}: inserisci un numero intero da {low} a {high}."),
    "kstab.error.number": ("{field}: enter a number from {low} to {high}.",
                           "{field}: inserisci un numero da {low} a {high}."),
    "kstab.error.flag": ("{field}: choose on or off.", "{field}: scegli sì o no."),
    "kstab.error.variables": ("Select from {low} to {high} numeric columns.",
                              "Seleziona da {low} a {high} colonne numeriche."),
    "kstab.error.once": ("Select each column only once.", "Seleziona ogni colonna una sola volta."),
    "kstab.error.missing": ('Column "{name}" is not in the table.', 'La colonna "{name}" non è nella tabella.'),
    "kstab.error.duplicate": ('More than one column is called "{name}".',
                              'Più di una colonna si chiama "{name}".'),
    "kstab.error.complex": ('Column "{name}" contains complex data.', 'La colonna "{name}" contiene dati complessi.'),
    "kstab.error.text": ('Column "{name}" contains text.', 'La colonna "{name}" contiene testo.'),
    "kstab.error.empty": ("No row has a number in every selected column.",
                          "Nessuna riga ha un numero in tutte le colonne scelte."),
    "kstab.error.rows": ("Use at most {limit} complete rows (this selection has {count}).",
                         "Usa al massimo {limit} righe complete (questa selezione ne ha {count})."),
    "kstab.error.constant": ('Column "{name}" is constant and cannot be standardized.',
                             'La colonna "{name}" è costante e non si può standardizzare.'),
    "kstab.error.tiny": ("There are only {count} complete rows: samples are too small for k = 2.",
                         "Ci sono solo {count} righe complete: i campioni sono troppo piccoli per k = 2."),
    "kstab.error.max_sample": ("With {count} complete rows a sample holds at most {largest} rows: "
                               "choose Maximum k up to {limit}.",
                               "Con {count} righe complete un campione contiene al massimo {largest} righe: "
                               "scegli un k massimo fino a {limit}."),
    "kstab.error.fraction": ("Each sample has {sample} of {count} rows and needs at least {needed} "
                             "(Maximum k + 1): raise the sample fraction.",
                             "Ogni campione ha {sample} righe su {count} e gliene servono almeno {needed} "
                             "(k massimo + 1): aumenta la frazione campionata."),
    "kstab.error.distinct": ("Maximum k cannot exceed the {count} distinct observations.",
                             "Il k massimo non può superare le {count} osservazioni distinte."),
    "kstab.error.cells": ("N × Maximum k must be at most {limit} ({count} rows × {k} = {product}).",
                          "N × k massimo deve essere al massimo {limit} ({count} righe × {k} = {product})."),
    "kstab.error.fits": ("This request needs {fits} K-means fits; the limit is {limit}. "
                         "Lower Resamples, Seed runs or the range of k.",
                         "Questa richiesta richiede {fits} fit K-means; il limite è {limit}. "
                         "Riduci i ricampionamenti, le ripetizioni con altri semi o l'intervallo di k."),
    "kstab.error.work": ("This request needs {work} work units; the limit is {limit}. "
                         "Lower Resamples, Seed runs, the range of k or the number of variables.",
                         "Questa richiesta richiede {work} unità di lavoro; il limite è {limit}. "
                         "Riduci i ricampionamenti, le ripetizioni con altri semi, l'intervallo di k "
                         "o il numero di variabili."),
    "kstab.error.matrix": ("The co-assignment matrix needs at most {limit} complete rows (this selection has {count}).",
                           "La matrice di co-assegnazione richiede al massimo {limit} righe complete "
                           "(questa selezione ne ha {count})."),
    "kstab.error.reference": ("No reference partition could be fitted for k = {low}–{high}. {reason}",
                              "Non è stato possibile calcolare nessuna partizione di riferimento per k = "
                              "{low}–{high}. {reason}"),
    "kstab.error.algorithm": ("Choose a K-means algorithm.", "Scegli un algoritmo K-means."),
    "kstab.error.iterations": ("Enter a whole number from 1 to 1000.", "Inserisci un numero intero da 1 a 1000."),
    "kstab.error.iteration_limit": ("Hartigan–Wong reached the maximum number of iterations.",
                                    "Hartigan–Wong ha raggiunto il limite di iterazioni."),
})

# Validate binary logistic model (0.96): captions and engine messages live in their own section.
from .logistic_validation_catalog import CAPTIONS as _LOGISTIC_VALIDATION_CAPTIONS  # noqa: E402
from .logistic_validation_catalog import MESSAGES as _LOGISTIC_VALIDATION_MESSAGES  # noqa: E402

CAPTIONS.update(_LOGISTIC_VALIDATION_CAPTIONS)
MESSAGES.update(_LOGISTIC_VALIDATION_MESSAGES)

# Bland–Altman for repeated pairs (0.96): method, fields and engine messages. Recipes keep the English keys and
# values; sheet titles, column headers and worksheet text stay literal.
CAPTIONS.update({
    "Bland–Altman for repeated pairs": "Bland–Altman per coppie ripetute",
    "Occasion": "Occasione",
    "Mode": "Modalità",
    "Coverage": "Copertura (%)",
    "Confidence intervals": "Intervalli di confidenza",
    "Log ratio": "Logaritmo del rapporto",
    "Subject diagnostics": "Diagnostica per soggetto",
})

MESSAGES.update({
    "barep.error.column": ("Choose a column for {field}.", "Scegli una colonna per {field}."),
    "barep.error.distinct": ("Choose two different columns for First and Second.",
                             "Scegli due colonne diverse per Prima variabile e Seconda variabile."),
    "barep.error.subject_column": ("Subject, First and Second must be different columns.",
                                   "Soggetto, Prima variabile e Seconda variabile devono essere colonne diverse."),
    "barep.error.occasion_column": ("Occasion must be a column other than Subject, First and Second.",
                                    "Occasione deve essere una colonna diversa da Soggetto, Prima variabile e "
                                    "Seconda variabile."),
    "barep.error.choice": ("Choose a valid value for {field}.", "Scegli un valore valido per {field}."),
    "barep.error.percent": ("{field} must be a number greater than 0 and less than 100.",
                            "{field} deve essere un numero maggiore di 0 e minore di 100."),
    "barep.error.whole": ("{field} must be a whole number from {low} to {high}.",
                          "{field} deve essere un numero intero da {low} a {high}."),
    "barep.error.missing": ('Column "{name}" is not in the table.', 'La colonna "{name}" non è nella tabella.'),
    "barep.error.duplicate": ('More than one column is called "{name}".', 'Più di una colonna si chiama "{name}".'),
    "barep.error.numbers": ('Column "{name}" must contain numbers.', 'La colonna "{name}" deve contenere numeri.'),
    "barep.error.finite": ('Column "{name}" has a value that is not a finite number in row {row}.',
                           'La colonna "{name}" ha un valore che non è un numero finito alla riga {row}.'),
    "barep.error.magnitude": ('Column "{name}" has a value outside −1e100 to 1e100 in row {row}.',
                              'La colonna "{name}" ha un valore fuori da −1e100 … 1e100 alla riga {row}.'),
    "barep.error.positive": ('Log ratio needs positive values: column "{name}" has {value} in row {row}.',
                             'Il logaritmo del rapporto richiede valori positivi: la colonna "{name}" ha {value} '
                             'alla riga {row}.'),
    "barep.error.repeated_occasion": ('Subject "{subject}" has occasion "{occasion}" in rows {a} and {b}. '
                                      "Each subject and occasion may hold one pair.",
                                      'Il soggetto "{subject}" ha l’occasione "{occasion}" alle righe {a} e {b}. '
                                      "Ogni soggetto e occasione può avere una sola coppia."),
    "barep.error.pairs": ("Use at most {limit} pairs (this selection has {count}).",
                          "Usa al massimo {limit} coppie (questa selezione ne ha {count})."),
    "barep.error.subjects": ("At least {low} subjects with complete pairs are needed; {count} found.",
                             "Servono almeno {low} soggetti con coppie complete; trovati {count}."),
    "barep.error.within": ("No subject has two complete pairs: the within-subject variance needs at least one "
                           "repeated pair.",
                           "Nessun soggetto ha due coppie complete: la varianza entro soggetto richiede almeno "
                           "una coppia ripetuta."),
    "barep.error.work": ("Bootstrap replicates × subjects = {a} × {b} exceeds the limit of {limit}.",
                         "Repliche bootstrap × soggetti = {a} × {b} supera il limite di {limit}."),
})
from .cluster_silhouette_text import CAPTIONS as _SILHOUETTE_CAPTIONS, MESSAGES as _SILHOUETTE_MESSAGES

CAPTIONS.update(_SILHOUETTE_CAPTIONS)
MESSAGES.update(_SILHOUETTE_MESSAGES)

# Intraclass correlation (0.97). Canonical recipes stay English; these captions are display text.
CAPTIONS.update({
    "Intraclass correlation": "Correlazione intraclasse",
    "Raters": "Valutatori",
    "Definition": "Definizione",
    "Unit": "Unità",
    "Bootstrap CI": "IC bootstrap",
    "Profile graph": "Grafico dei profili",
    "Absolute agreement": "Accordo assoluto",
    "Consistency": "Coerenza",
    "Single measure": "Misura singola",
    "Mean of raters": "Media dei valutatori",
})

MESSAGES.update({
    "icc.error.raters_columns": ("Choose columns for {field}.", "Scegli le colonne per {field}."),
    "icc.error.raters_min": ("Choose at least two columns for {field}.", "Scegli almeno due colonne per {field}."),
    "icc.error.raters_once": ("Choose each column of {field} only once.",
                              "Scegli ogni colonna di {field} una sola volta."),
    "icc.error.raters_max": ("Use at most {limit} raters (this selection has {count}).",
                             "Usa al massimo {limit} valutatori (questa selezione ne ha {count})."),
    "icc.error.subject_column": ("Choose a column for {field}.", "Scegli una colonna per {field}."),
    "icc.error.subject_overlap": ("{field} must be a column other than the {raters}.",
                                  "{field} deve essere una colonna diversa dai {raters}."),
    "icc.error.choice": ("Choose a valid value for {field}.", "Scegli un valore valido per {field}."),
    "icc.error.percent": ("{field} must be a number greater than 0 and less than 100.",
                          "{field} deve essere un numero maggiore di 0 e minore di 100."),
    "icc.error.whole": ("{field} must be a whole number from {low} to {high}.",
                        "{field} deve essere un numero intero da {low} a {high}."),
    "icc.error.missing": ('Column "{name}" is not in the table.', 'La colonna "{name}" non è nella tabella.'),
    "icc.error.duplicate": ('More than one column is called "{name}".', 'Più di una colonna si chiama "{name}".'),
    "icc.error.numbers": ('Column "{name}" must contain numbers.', 'La colonna "{name}" deve contenere numeri.'),
    "icc.error.finite": ('Column "{name}" has a value that is not a finite number in row {row}.',
                         'La colonna "{name}" ha un valore che non è un numero finito alla riga {row}.'),
    "icc.error.magnitude": ('Column "{name}" has a value outside −1e100 to 1e100 in row {row}.',
                            'La colonna "{name}" ha un valore fuori da −1e100 … 1e100 alla riga {row}.'),
    "icc.error.rows": ("Use at most {limit} rows (this selection has {count}).",
                       "Usa al massimo {limit} righe (questa selezione ne ha {count})."),
    "icc.error.few": ("At least {low} complete rows are needed; {count} found.",
                      "Servono almeno {low} righe complete; trovate {count}."),
    "icc.error.work": ("Bootstrap would resample {cells} cells (replicates × rows × raters); the limit is {limit}.",
                       "Il bootstrap ricampionerebbe {cells} celle (repliche × righe × valutatori); il limite è "
                       "{limit}."),
    "icc.summary.counts": ("{complete} complete subjects · {raters} raters · incomplete rows left out: {excluded}",
                           "{complete} soggetti completi · {raters} valutatori · righe incomplete escluse: "
                           "{excluded}"),
    "icc.summary.order": ("Order of the raters: {names}", "Ordine dei valutatori: {names}"),
    "icc.summary.unit": ("{definition}, {unit}", "{definition}, {unit}"),
    "icc.summary.none": ("Choose at least two rater columns.", "Scegli almeno due colonne di valutatori."),
    "icc.summary.caption": ("Summary", "Riepilogo"),
})

# Precision–recall curve (0.97): captions and engine messages live in their own section.
from .precision_recall_catalog import CAPTIONS as _PRECISION_RECALL_CAPTIONS  # noqa: E402
from .precision_recall_catalog import MESSAGES as _PRECISION_RECALL_MESSAGES  # noqa: E402

CAPTIONS.update(_PRECISION_RECALL_CAPTIONS)
MESSAGES.update(_PRECISION_RECALL_MESSAGES)

# Empirical cumulative distribution: captions and engine messages live in their own section.
from .ecdf_catalog import CAPTIONS as _ECDF_CAPTIONS  # noqa: E402
from .ecdf_catalog import MESSAGES as _ECDF_MESSAGES  # noqa: E402

CAPTIONS.update(_ECDF_CAPTIONS)
MESSAGES.update(_ECDF_MESSAGES)

# Two-factor interaction plot: captions and engine messages live in their own section.
from .interaction_plot_catalog import CAPTIONS as _INTERACTION_PLOT_CAPTIONS  # noqa: E402
from .interaction_plot_catalog import MESSAGES as _INTERACTION_PLOT_MESSAGES  # noqa: E402

CAPTIONS.update(_INTERACTION_PLOT_CAPTIONS)
MESSAGES.update(_INTERACTION_PLOT_MESSAGES)

# Raincloud plot: captions and engine messages live in their own section.
from .raincloud_plot_catalog import CAPTIONS as _RAINCLOUD_CAPTIONS  # noqa: E402
from .raincloud_plot_catalog import MESSAGES as _RAINCLOUD_MESSAGES  # noqa: E402

CAPTIONS.update(_RAINCLOUD_CAPTIONS)
MESSAGES.update(_RAINCLOUD_MESSAGES)

# Pareto plot: captions and engine messages live in their own section.
from .pareto_plot_catalog import CAPTIONS as _PARETO_CAPTIONS  # noqa: E402
from .pareto_plot_catalog import MESSAGES as _PARETO_MESSAGES  # noqa: E402

CAPTIONS.update(_PARETO_CAPTIONS)
MESSAGES.update(_PARETO_MESSAGES)

# Two-way ANOVA from cell summaries: captions and engine messages live in their own section.
from .summary_twoway_catalog import CAPTIONS as _SUMMARY_TWOWAY_CAPTIONS  # noqa: E402
from .summary_twoway_catalog import MESSAGES as _SUMMARY_TWOWAY_MESSAGES  # noqa: E402

CAPTIONS.update(_SUMMARY_TWOWAY_CAPTIONS)
MESSAGES.update(_SUMMARY_TWOWAY_MESSAGES)

# Weighted log-rank (Tarone–Ware and Fleming–Harrington): captions and messages live in their own section.
from .weighted_logrank_catalog import CAPTIONS as _WEIGHTED_LOGRANK_CAPTIONS  # noqa: E402
from .weighted_logrank_catalog import MESSAGES as _WEIGHTED_LOGRANK_MESSAGES  # noqa: E402

CAPTIONS.update(_WEIGHTED_LOGRANK_CAPTIONS)
MESSAGES.update(_WEIGHTED_LOGRANK_MESSAGES)

MESSAGES.update({
    "partial.error.variables": ("Choose 2 to 12 distinct variables.", "Scegli da 2 a 12 variabili distinte."),
    "partial.error.covariates": ("Choose 1 to 8 distinct covariates.", "Scegli da 1 a 8 covariate distinte."),
    "partial.error.overlap": ("{name} cannot be both a variable and a covariate.",
                              "{name} non può essere sia una variabile sia una covariata."),
    "partial.error.missing": ("Choose a column for {field}.", "Scegli una colonna per {field}."),
    "partial.error.numeric": ('Column "{name}" is not numeric.', 'La colonna "{name}" non è numerica.'),
    "partial.error.flag": ("Choose yes or no for {field}.", "Scegli sì o no per {field}."),
    "partial.error.method": ("Choose Pearson or Spearman.", "Scegli Pearson o Spearman."),
    "partial.error.constant": ("Covariate {name} is constant on the rows used by this correlation.",
                               "La covariata {name} è costante sulle righe usate da questa correlazione."),
    "partial.error.redundant": ("Covariate {name} repeats {other}.", "La covariata {name} ripete {other}."),
    "partial.error.rank": ("The covariates do not have full rank on the rows used by this correlation.",
                           "Le covariate non hanno rango pieno sulle righe usate da questa correlazione."),
    "partial.error.rows": ("N − k − 2 must be positive. This selection leaves {n} complete rows and {k} covariates.",
                           "N − k − 2 deve essere positivo. Questa selezione lascia {n} righe complete e {k} covariate."),
    "partial.error.scatter": ("The residual scatter needs exactly two variables.",
                              "Il grafico dei residui richiede esattamente due variabili."),
    "partial.note": (
        "Pearson correlates the residuals of each variable on the covariates, including an intercept. "
        "Spearman applies the same calculation to average ranks, and its p value is approximate. "
        "The Fisher interval uses standard error 1/√(N − k − 3) and stays empty when it cannot be estimated. "
        "The residual scatter is drawn only for exactly two variables.",
        "Pearson correla i residui di ogni variabile sulle covariate, con intercetta. "
        "Spearman applica lo stesso calcolo ai ranghi medi e il suo valore p è approssimato. "
        "L’intervallo di Fisher usa l’errore standard 1/√(N − k − 3) e resta vuoto quando non è stimabile. "
        "Il grafico dei residui si disegna solo per due variabili esatte.",
    ),
})
