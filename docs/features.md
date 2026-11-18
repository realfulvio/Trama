# Funzionalità di Trama

[Presentazione](../README.md) · [Guida rapida](getting-started.md) · [Compatibilità](compatibility.md)

Trama collega dati, analisi, grafici e layout in un progetto locale. Questa panoramica descrive le famiglie disponibili nella 0.85.0 beta; le opzioni e i limiti dei singoli metodi restano espliciti nei dialoghi e nei risultati.

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

## Confronti e inferenza

Test t indipendenti, appaiati e di Welch; test t lognormali per dati positivi, con rapporto fra medie geometriche e intervallo di confidenza ([guida](lognormal-tests-070.md)); test di equivalenza TOST per uno o due campioni, appaiati, Student e Welch, con zona di equivalenza dichiarata dall'utente ([guida](equivalence-tost-071.md)); test di rango; ANOVA ordinaria, di Welch e Brown–Forsythe; misure ripetute, Friedman, Kruskal–Wallis e ANOVA multifattoriale. Confronti multipli e correzioni, comprese coppie selezionate e controlli del tasso di false scoperte nei flussi supportati.

I test esatti hanno limiti di calcolo dichiarati; quando è prevista una scelta automatica il risultato indica il metodo usato e l'eventuale motivo dell'approssimazione. I modelli misti REML gestiscono dati mancanti e offrono correzioni Satterthwaite e Kenward–Roger nei disegni supportati.

Sono disponibili normalità e Q–Q, screening di outlier ROUT su modello costante e Grubbs, tabelle di contingenza e misure diagnostiche. Per le tabelle 2×2 sono disponibili, fra gli altri, intervalli Koopman per il rischio relativo e Baptista–Pike per l'odds ratio.

## Regressioni, curve e calibrazione

- Regressione lineare, confronto fra rette, Deming, regressioni multiple OLS (anche pesate con pesi fissi gaussiani: 1/|Y|, 1/Y², 1/|Y|^K, 1/SD² o colonna di pesi), logistiche e Poisson con esposizione e diagnostica.
- 118 equazioni a catalogo in 14 famiglie; pesi osservati e IRLS dove supportati, vincoli, diagnostica e bande puntuali.
- [Intervalli dei parametri nei fit non lineari](nonlinear-parameter-intervals.md): Wald a livello configurabile e profili extra-SS asimmetrici nei fit indipendenti, inclusi i pesi osservati e quelli finali congelati IRLS, con stati per ciascun estremo e annullamento.
- [Profili dei parametri per equazioni personalizzate](custom-parameter-profiles.md), con coefficienti fissi, vincoli, SD relative, stati per ogni estremo e annullamento.
- [Profili congiunti delle equazioni globali personalizzate](global-custom-parameter-profiles.md): coefficienti condivisi o locali, vincoli per serie e gradi di libertà dell'intero fit; calcolo annullabile con stati distinti per radici, vincoli e limiti non determinati.
- Fit globali del catalogo con parametri condivisi e vincoli per singola serie; equazioni personalizzate e fit globali personalizzati, con bande puntuali di confidenza o predizione e previsioni per nuove X per serie dal fit congiunto.
- [Equazioni condizionali](conditional-equations-081.md) nei fit personalizzati, singoli e globali: modelli a tratti con `if(...)` e soglie note tenute fisse (i punti di cambio non vengono stimati), colonna del ramo e curve senza tratti fra i rami.
- Confronti fra modelli, AICc, calibrazione diretta e inversa con intervalli nei modelli supportati, spline e LOWESS.
- Adattamento robusto di curve (perdita Cauchy, Huber o Soft L1, scala fissa o MAD pilota), con pesi di influenza per punto, confronto facoltativo con il fit ordinario e grafico di curva, residui o pesi; descrittivo, senza errori standard né p ([guida](robust-curve-073.md)).

L'identificabilità, il dominio del modello, i vincoli attivi e il metodo di pesatura possono rendere indisponibile un intervallo anche quando la stima è calcolabile. Le note dei risultati distinguono questi casi.

## Sopravvivenza ed esplorazione multivariata

Kaplan–Meier, tabelle a rischio, confronti log-rank e Gehan–Breslow–Wilcoxon, Cox con profili e residui. Curve ROC e confronto DeLong appaiato; Bland–Altman anche con rapporti geometrici.

PCA con scree, scores, loadings e biplot; K-means con selezione del numero di gruppi e consenso a 17 indici; clustering gerarchico, dendrogrammi, heat map, matrici di correlazione ed [ellissi di confidenza con stili per gruppo](confidence-ellipses.md). Correlazione di Pearson, Spearman o Kendall con risultati dettagliati opzionali; correlazione di più risposte contro un controllo; confronto di due correlazioni di Pearson indipendenti sulla scala z di Fisher ([guida](correlation-details.md)).

Nel consenso K-means, **Scala di Krzanowski–Lai** usa di default la correzione per il numero di variabili. **WSS senza riscalatura** usa il rapporto assoluto fra due cali consecutivi della somma dei quadrati entro i gruppi. Il foglio dei risultati lo identifica come **WSS-drop ratio** e il rapporto occupa un solo voto nel consenso.

## Controllo delle false scoperte

[Control false discoveries](fdr-control.md) applica BH, BY o BKY a due stadi a più colonne p e famiglie esplicite. Distingue p mancanti e famiglie vuote e offre un grafico diagnostico facoltativo. I p aggiustati BKY dipendono dal livello scelto; quelli BH e BY no.

## Elaborazione dei dati e simulazione

Trasformazioni, normalizzazione, baseline anche con repliche, frazioni del totale, potatura di righe, scambio XY, frequenze, area sotto la curva e picchi. Studi Monte Carlo con seed riproducibile, avanzamento e annullamento.

## Grafici e figure

Grafici XY con più serie e due assi Y, barre d'errore anche asimmetriche, Column e Grouped, pile e pile al 100%, punti individuali, box e violini, prima/dopo e traiettorie, forest plot, bubble plot e grafici di composizione.

Formattazione di assi, serie, gruppi e legende; Inspector con anteprima; confronti statistici collegati al grafico, parentesi, stelle e lettere nei metodi supportati. Annotazioni e forme native, selezione e disposizione degli oggetti, tratteggi, frecce, riempimenti e colori distinti.

[Tacche aggiuntive, linee e fasce sugli assi](axis-guides.md) supportano assi numerici primari lineari o logaritmici, etichette letterali e anteprima modificabile. Le etichette sul bordo opposto possono sovrapporsi a quelle di un secondo asse Y: la guida descrive il limite.

Layout fino a 12 pannelli; export PNG, TIFF, SVG, PDF e PDF multipagina. Le porzioni vettoriali compatibili restano vettoriali negli export nativi; una heat map rasterizzata o una vista importata non diventa automaticamente un disegno nativo.

## Interoperabilità e verifiche

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

### Test t da statistiche riassuntive

**Group Comparison → Unpaired t-test from summaries** confronta due gruppi
indipendenti usando media aritmetica, SD/SEM/CV (%) e numerosità. Offre Welch
e Student, differenza ipotizzata, intervallo bilaterale e grafico della
differenza, senza ricostruire osservazioni individuali.
[Istruzioni e limiti](summary-ttest.md).

