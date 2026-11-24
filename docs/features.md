# Funzionalità di Trama

[Presentazione](../README.md) · [Guida rapida](getting-started.md) · [Compatibilità](compatibility.md)

Trama collega dati, analisi, grafici e layout in un progetto locale. Questa panoramica descrive le famiglie disponibili nella 0.93.0 beta; le opzioni e i limiti dei singoli metodi restano espliciti nei dialoghi e nei risultati.

Il [confronto di due varianze](variance-ratio-079.md) offre intervalli esatti e una figura facoltativa.

Le [famiglie di esperimenti](experiment-families.md) si duplicano o si salvano come progetto autonomo con tutto ciò da cui dipendono.

Le [analisi collegate](analysis-chains.md) usano una tabella di risultati come ingresso di un’analisi successiva e propagano le modifiche alla sorgente. La copia indipendente **Usa risultato come dati** rimane disponibile.

Le [ricette gerarchiche ZIP supportate](hierarchical-import.md) diventano analisi native modificabili: trasformazioni, clustering di righe e colonne, heat map e report si ricalcolano dai dati importati. La formattazione nativa non riproduce ogni dettaglio del documento originale.

## Interfaccia

Una [schermata di avvio con cerchio animato](startup-screen.md) accompagna il caricamento e si chiude quando la finestra principale è pronta.

**Impostazioni → Tema…** permette di scegliere Tema standard o Tema Moderno. Standard rimane il predefinito. Moderno dispone griglia, anteprima del grafico e ispettore nello stesso spazio; il tema si applica al prossimo avvio e non cambia dati, analisi o figure esportate. [Guida ai temi](interface-themes.md).

L’[editor delle legende](graph-legends.md) modifica titolo, colonne, cornice ed etichette dei grafici nativi con anteprima.

## Tabelle e progetti

- Tabelle XY, Column, Grouped, Nested, Contingency, Survival, Parts of whole e Multiple variables.
- Selezione di intervalli, repliche in sottocolonne, copia/incolla con Excel, incolla speciale e trasposizione, annulla/ripeti ed esclusione di celle.
- Formule nel foglio, costanti dai fogli Info, risultati riutilizzabili come dati, più progetti e navigazione fra fogli.
- Importazione CSV, TSV e XLSX; salvataggio di dati, ricette e presentazione nel formato `.alab`.
- [Rimodella lungo e largo](reshape-long-wide.md) trasforma la struttura di un foglio con anteprima e conserva la corrispondenza con le righe di origine.

## Confronti e inferenza

Il [test di permutazione per la differenza tra medie](mean-permutation-test.md) supporta campioni indipendenti e appaiati, enumerazione esatta e Monte Carlo riproducibile. Il [test di Yuen per medie troncate](yuen-trimmed-means.md) confronta due campioni indipendenti con medie troncate, errore standard winsorizzato e intervallo di confidenza. Il [kappa di Cohen](cohen-kappa.md) misura la concordanza tra due valutatori con pesi lineari, quadratici o senza pesi, intervallo bootstrap e matrice di concordanza esportabile.

Test t indipendenti, appaiati e di Welch; test t lognormali per dati positivi, con rapporto fra medie geometriche e intervallo di confidenza ([guida](lognormal-tests-070.md)); test di equivalenza TOST per uno o due campioni, appaiati, Student e Welch, con zona di equivalenza dichiarata dall'utente ([guida](equivalence-tost-071.md)); test di rango; ANOVA ordinaria, di Welch e Brown–Forsythe; misure ripetute, Friedman, Kruskal–Wallis e ANOVA multifattoriale. Confronti multipli e correzioni, comprese coppie selezionate e controlli del tasso di false scoperte nei flussi supportati.

I test esatti hanno limiti di calcolo dichiarati; quando è prevista una scelta automatica il risultato indica il metodo usato e l'eventuale motivo dell'approssimazione. I modelli misti REML gestiscono dati mancanti e offrono correzioni Satterthwaite e Kenward–Roger nei disegni supportati.

Sono disponibili normalità e Q–Q, screening di outlier ROUT su modello costante e Grubbs, tabelle di contingenza e misure diagnostiche. Per le tabelle 2×2 sono disponibili, fra gli altri, intervalli Koopman per il rischio relativo e Baptista–Pike per l'odds ratio.

Il [test binomiale esatto](exact-binomial.md) confronta due conteggi osservati con una proporzione attesa e riporta i valori p e l’intervallo di Clopper–Pearson.

### Potenza e numerosità da medie e SD

**Analizza → Potenza e numerosità…** pianifica uno studio con t a un campione, t appaiato, t indipendente (con allocazione esatta A:B) o ANOVA a una via bilanciata, partendo dalle medie e dalle SD attese oppure da un effetto standardizzato. Cerca la numerosità minima o calcola la potenza e può disegnare la curva di potenza come grafico nativo. [Conversione, allocazione e assunzioni](power-from-summary.md).

## Regressioni, curve e calibrazione

- Regressione lineare, confronto fra rette, Deming, regressioni multiple OLS (anche pesate con pesi fissi gaussiani: 1/|Y|, 1/Y², 1/|Y|^K, 1/SD² o colonna di pesi), logistiche e Poisson con esposizione e diagnostica. [Validazione fuori campione del modello logistico binario](logistic-validation.md): validazione incrociata a K fold stratificata o con colonna di fold, Brier, log loss, AUC ROC, precisione media, matrice di confusione e calibrazione per classi. [Regressione binomiale negativa (NB2)](nb2-regression.md) per conteggi sovradispersi: esposizione, predittori categorici, α stimata per massima verosimiglianza o fissa, IRR con intervalli di Wald e residui di Pearson.
- [Regressione logistica ordinale](ordinal-logit.md) a odds proporzionali con ordine esplicito, soglie e probabilità stimate per profilo.
- 118 equazioni a catalogo in 14 famiglie; pesi osservati e IRLS dove supportati, vincoli, diagnostica e bande puntuali.
- [Intervalli dei parametri nei fit non lineari](nonlinear-parameter-intervals.md): Wald a livello configurabile e profili extra-SS asimmetrici nei fit indipendenti, inclusi i pesi osservati e quelli finali congelati IRLS, con stati per ciascun estremo e annullamento.
- [Profili dei parametri per equazioni personalizzate](custom-parameter-profiles.md), con coefficienti fissi, vincoli, SD relative, stati per ogni estremo e annullamento.
- [Profili congiunti delle equazioni globali personalizzate](global-custom-parameter-profiles.md): coefficienti condivisi o locali, vincoli per serie e gradi di libertà dell'intero fit; calcolo annullabile con stati distinti per radici, vincoli e limiti non determinati.
- Fit globali del catalogo con parametri condivisi e vincoli per singola serie; equazioni personalizzate e fit globali personalizzati, con bande puntuali di confidenza o predizione e previsioni per nuove X per serie dal fit congiunto.
- [Equazioni condizionali](conditional-equations-081.md) nei fit personalizzati, singoli e globali: modelli a tratti con `if(...)` e soglie note tenute fisse (i punti di cambio non vengono stimati), colonna del ramo e curve senza tratti fra i rami.
- Confronti fra modelli, AICc, calibrazione diretta e inversa con intervalli nei modelli supportati e [calibrazione razionale Padé (1,1)](pade-calibration.md), spline e LOWESS.
- [Pipeline di operazioni su curve XY](curve-pipeline.md) in Smussa / deriva / integra: differenze prime e seconde ai punti medi, integrale cumulato con trapezi rispetto a una baseline e smussamento Savitzky–Golay combinabile, per blocchi separati dalle righe senza Y; risultato con righe sorgente, unità e note, descrittivo e non un modello adattato.
- Adattamento robusto di curve (perdita Cauchy, Huber o Soft L1, scala fissa o MAD pilota), con pesi di influenza per punto, confronto facoltativo con il fit ordinario e grafico di curva, residui o pesi; descrittivo, senza errori standard né p ([guida](robust-curve-073.md)).

L'identificabilità, il dominio del modello, i vincoli attivi e il metodo di pesatura possono rendere indisponibile un intervallo anche quando la stima è calcolabile. Le note dei risultati distinguono questi casi.

## Sopravvivenza ed esplorazione multivariata

Kaplan–Meier, tabelle a rischio, [bande simultanee Hall–Wellner](survival-simultaneous-bands.md) (conservative, una per curva), confronti log-rank e Gehan–Breslow–Wilcoxon, Cox con profili e residui, compresi [Schoenfeld scalati e Cox–Snell](cox-fit-diagnostics.md). Il [Cox condizionale esatto](cox-exact-ties.md) gestisce i pari tempo e riporta coefficienti e modello, fino a 2.000 righe e 8 colonne del modello. L’[analisi dei rischi competitivi](competing-risks.md) include incidenza cumulativa di Aalen–Johansen, intervalli puntuali, stime a tempi scelti, test di Gray omnibus e a coppie con Holm e grafici per una o tutte le cause. [Regressione Weibull AFT](weibull-aft.md) con censura a destra, forma stimata o fissa, rapporti dei tempi, mediane e curve di sopravvivenza per profilo. [Sopravvivenza media ristretta (RMST)](restricted-mean-survival.md) con confronto di due gruppi a un orizzonte comune, differenza e rapporto tra le aree sotto le curve Kaplan–Meier. Sono disponibili curve ROC, DeLong appaiato e [confronti ROC indipendenti](independent-roc-curves.md) con area completa, parziale e parziale standardizzata. La [curva precisione–richiamo](precision-recall.md) valuta punteggi esterni di uno o due strumenti sugli stessi campioni, con precisione media, soglie, prevalenza e bootstrap appaiato stratificato. Bland–Altman include i rapporti geometrici e la variante [per coppie ripetute](bland-altman-repeated.md), con varianza entro e tra soggetti e bootstrap per soggetti.

In Kaplan–Meier, **Confronti a coppie** permette di confrontare tutte le coppie, scegliere un controllo o indicare le singole coppie. Con Benjamini–Hochberg, Benjamini–Yekutieli o Benjamini–Krieger–Yekutieli a due stadi, imposta la FDR desiderata in percentuale. Il foglio dei confronti conserva i p grezzi, i p corretti e l’esito di ciascun test. Il riepilogo FDR riporta il numero di test effettivamente usati per ogni risposta. Per il metodo a due stadi i p corretti dipendono dalla soglia scelta.


La [correlazione intraclasse](icc.md) quantifica l’accordo assoluto o la coerenza di più valutatori su misure continue (misura singola o media dei valutatori), con tabella ANOVA, grafico dei profili per soggetto e intervallo bootstrap per soggetti facoltativo, condizionato al pannello di valutatori osservato.

PCA con scree, scores, loadings e biplot, [colori per gruppo, contorni e report facoltativi](pca-reports.md); [regressione sulle componenti principali](pca-regression-087.md) e ripristino di [ricette PCA compatibili](compatibility.md); [K-means con Lloyd, Hartigan–Wong e MacQueen](kmeans-algorithms.md), con selezione del numero di gruppi e consenso a 17 indici; [stabilità K-means per ricampionamento e semi](kmeans-stability.md), con ARI, Jaccard per gruppo, accordo per osservazione e matrice di co-assegnazione; clustering gerarchico con [ordine ottimale delle foglie](leaf-ordering.md), dendrogrammi, heat map, matrici di correlazione ed [ellissi di confidenza con stili per gruppo](confidence-ellipses.md). Correlazione di Pearson, Spearman o Kendall con risultati dettagliati opzionali; correlazione di più risposte contro un controllo; confronto di due correlazioni di Pearson indipendenti sulla scala z di Fisher ([guida](correlation-details.md)). [Correlazione a misure ripetute](repeated-measures-correlation.md) entro soggetto, con intercette per soggetto, pendenza comune e bootstrap facoltativo per soggetti interi.

Per ogni k calcolato consulta assegnazioni, centri e metriche e affianca WSS, Silhouette e Gap nel grafico. Una PCA collegata alla tabella delle assegnazioni si aggiorna dopo una modifica della sorgente.

La [meta-analisi](meta-analysis.md) combina differenze o rapporti degli studi con i loro errori standard. Riporta un forest plot modificabile, l’eterogeneità e, su richiesta, l’analisi escludendo uno studio alla volta.
La [silhouette dei cluster](cluster-silhouette-092.md) valuta una partizione già assegnata e riporta risultati per osservazione e per gruppo.


Nel consenso K-means, **Scala di Krzanowski–Lai** usa di default la correzione per il numero di variabili. **WSS senza riscalatura** usa il rapporto assoluto fra due cali consecutivi della somma dei quadrati entro i gruppi. Il foglio dei risultati lo identifica come **WSS-drop ratio** e il rapporto occupa un solo voto nel consenso.

## Controllo delle false scoperte

[Control false discoveries](fdr-control.md) applica BH, BY o BKY a due stadi a più colonne p e famiglie esplicite. Distingue p mancanti e famiglie vuote e offre un grafico diagnostico facoltativo. I p aggiustati BKY dipendono dal livello scelto; quelli BH e BY no.

## Elaborazione dei dati e simulazione

Trasformazioni, normalizzazione, baseline anche con repliche, frazioni del totale, potatura di righe, scambio XY, frequenze, area sotto la curva e picchi. Studi Monte Carlo con seed riproducibile, avanzamento e annullamento.

## Grafici e figure

Le [serie XY miste](xy-mixed-series.md) combinano punti, linee, gradini e barre raggruppate sui due assi Y. Formato grafico controlla la larghezza in unità X e l’Ispettore permette di cambiare colore, etichetta e visibilità delle serie supportate. Barre e gradini restano vettoriali nelle esportazioni.

Grafici XY con più serie e due assi Y, barre d'errore anche asimmetriche, Column e Grouped, pile e pile al 100%, punti individuali, box e violini (anche raggruppati per categoria e serie), prima/dopo e traiettorie, forest plot, bubble plot e grafici di composizione.

Formattazione di assi, serie, gruppi e legende; Inspector con anteprima; confronti statistici collegati al grafico, parentesi, stelle e lettere nei metodi supportati. Annotazioni e forme native, selezione e disposizione degli oggetti, tratteggi, frecce, riempimenti e colori distinti.

[Tacche aggiuntive, linee e fasce sugli assi](axis-guides.md) supportano assi numerici primari lineari o logaritmici, etichette letterali e anteprima modificabile. Le etichette sul bordo opposto possono sovrapporsi a quelle di un secondo asse Y: la guida descrive il limite.

Gli [assi secondari sincronizzati](linked-axes.md) mostrano la stessa coordinata in un’altra unità (moltiplicatore e scostamento) sul bordo superiore o destro dei grafici XY, di regressione e di sopravvivenza e sull’asse dei valori di Column e Grouped. Seguono spostamento, zoom e inversione dell’asse principale, non cambiano dati né calcoli e restano vettoriali nell’esportazione.

Layout fino a 12 pannelli; export PNG, TIFF, SVG, PDF e PDF multipagina. Le porzioni vettoriali compatibili restano vettoriali negli export nativi; una heat map rasterizzata o una vista importata non diventa automaticamente un disegno nativo.

## Interoperabilità e verifiche

I [grafici a dispersione importati compatibili](release-088.md) conservano coordinate modificabili, colori per categoria e assi lineari.

L’importazione dei formati legacy è parziale e dipende dalla struttura del documento: vedi [formati e limiti](compatibility.md). L'[archivio delle versioni](release-history.md) conserva i dettagli storici; la [documentazione tecnica](coverage.md) approfondisce metodi e scelte numeriche.

La 0.80.0 beta è stata verificata con 2.421 test sia su Linux sia su Windows, con gli smoke GUI completi e con il portabile nativo. [Collaudi e limiti](validation-080.md). Il dialogo TOST è stato collaudato a 1024×768 e 1920×1200 reali. Questa evidenza riguarda i casi provati e non equivale a una validazione per qualsiasi impiego. Vedi [validazione e responsabilità](legal.md) e [rapporto TOST](validation-tost-086.md).

La regressione lineare offre anche [stime di Y a X fissata e intervalli inversi di X a Y fissata](linear-point-estimates.md), compresi gli intervalli asimmetrici dell’intercetta X.

Il [rapporto 0.71](validation-071.md) conserva i precedenti collaudi della UI, inclusa la scalatura Windows 125/150%; tali prove non sono state ripetute per il nuovo dialogo TOST.

Spearman dettagliato e contro controllo: test esatti con legami fino a 17 coppie complete, entro limiti espliciti di lavoro e memoria, con annullamento e compatibilità delle ricette precedenti. Vedi [guida](spearman-exact-extended.md).

Normalità e lognormalità con quattro test, pannelli Q–Q affiancati e confronto dei due modelli mediante verosimiglianze, AIC e pesi relativi. Vedi [guida](lognormality.md).

### ANOVA da statistiche riassuntive

**Group Comparison → One-way ANOVA from summaries** confronta gruppi indipendenti
partendo da media, SD/SEM/CV (%) e numerosità, anche in sottocolonne di un foglio
Grouped. Offre ANOVA ordinaria e confronti Tukey–Kramer, Holm o Bonferroni,
con grafico delle medie e intervalli basati sulla varianza aggregata.
[Istruzioni e limiti](summary-anova.md).

### Test t da misure individuali

**Group Comparison → t-test** accetta una colonna di misura con un gruppo oppure
due colonne di misura separate. Per il disegno appaiato si seleziona il soggetto
e si usano le coppie complete. Welch e Student escludono i mancanti per campione.
Il livello di confidenza si applica al foglio e al grafico di stima. L'alternativa
direzionale cambia il p del test, e l'intervallo resta bilaterale. I dettagli
del test appaiato includono g di Hedges e il test di Pearson per correlazione
positiva tra le misure appaiate.

### Test t da statistiche riassuntive

**Group Comparison → Unpaired t-test from summaries** confronta due gruppi
indipendenti usando media aritmetica, SD/SEM/CV (%) e numerosità. Offre Welch
e Student, differenza ipotizzata, intervallo bilaterale e grafico della
differenza, senza ricostruire osservazioni individuali.
[Istruzioni e limiti](summary-ttest.md).

