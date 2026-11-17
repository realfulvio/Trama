# Trama 0.73.0 beta

Questa è una build beta: alcune funzionalità sono incomplete e possono esserci errori. Le immagini usano dati sintetici.

## Un nuovo spazio di lavoro, facoltativo

**Impostazioni → Tema…** offre **Tema standard** e **Tema Moderno**. Standard resta il predefinito. Moderno riunisce griglia, anteprima del grafico collegato e ispettore, con barra dei comandi compatta e navigatore semplificato. La scelta vale dal prossimo avvio. Ridimensionare l'anteprima non cambia la figura da esportare; Applica conferma lo stile, Annulla conserva quello precedente. [Guida](interface-themes.md).

## Heat map e grafici Q–Q

- Gradienti personalizzati singoli e doppi, opacità e colori delle categorie conservati per livello.
- Legenda orientabile, titolo, inversione e tick espliciti; formati numerici fisso e scientifico.
- Etichette delle celle con precisione, prefisso/suffisso e colori; spaziature fra righe/colonne e assi più leggibili.
- Pannelli Q–Q normale e lognormale con titoli, assi, punti e retta di riferimento formattabili separatamente, anteprima e ripristino.

[Heat map](heatmap-colors-072.md) · [Geometria](heatmap-layout.md) · [Pannelli Q–Q](qq-panels.md)

## Analisi e preparazione dei dati

- **Fit robusti** Cauchy, Huber e Soft L1, scala fissa o Pilot MAD, confronto con il fit ordinario e recupero del dialogo in caso di errore. Gli intervalli classici non vengono attribuiti automaticamente al fit robusto. [Guida](robust-curve-073.md).
- **Normalizzazione su riferimenti** con repliche o valori riepilogati, trasformazione coerente degli errori e riferimenti espliciti. L'incertezza dei riferimenti non viene propagata. [Guida](reference-normalization.md).
- **Intervalli inversi non lineari** per One-phase decay e quattro modelli 4PL a pendenza variabile, entro il dominio osservato. Eventuali componenti separate rimangono separate; i casi non identificabili o fuori budget vengono dichiarati. [Guida](nonlinear-inverse-intervals-073.md).
- **Correlazioni dettagliate**, confronto con un controllo e confronto di due Pearson indipendenti. Spearman esatto con legami fino a 17 coppie entro limiti di lavoro/memoria, con annullamento sul worker. [Guida](correlation-details.md) · [Budget esatto](spearman-exact-extended.md).
- **Normalità/lognormalità** con Q–Q e confronto AIC delle due distribuzioni; ANOVA ordinaria, Welch e Brown–Forsythe sui logaritmi per dati positivi. [Distribuzioni](lognormality.md) · [ANOVA lognormale](lognormal-anova.md).
- **Analisi da riepiloghi**: test t indipendenti Student/Welch e ANOVA ordinaria/Welch/Brown–Forsythe da media, SD/SEM/CV e N, con confronti multipli nei metodi compatibili. Non vengono ricostruite osservazioni artificiali, appaiamenti o residui. [Test t](summary-ttest.md) · [ANOVA](summary-unequal-anova.md).

La revisione d'integrazione corregge anche il traboccamento della somma delle precisioni e la perdita dei gradi di libertà di Welch con varianze molto piccole; gli oracoli indipendenti verificano i risultati a più scale.

## Compatibilità e limiti

Le scelte nuove sono facoltative; i percorsi legacy verificati sono conservati. Salvare una ricetta con funzioni nuove può richiedere questa versione per ricalcolarla. Il tema è una preferenza locale, esterna al progetto `.alab`.

L'interfaccia è disponibile in italiano e inglese; alcune tabelle, legende e messaggi mantengono l'inglese. La beta non costituisce validazione clinica o certificazione regolatoria. L'importazione di formati legacy rimane limitata ai contenuti supportati: non viene dichiarata compatibilità completa.

[Collaudo della build](validation-073.md) · [Installazione e primi passi](getting-started.md) · [Tutte le funzionalità](features.md)

