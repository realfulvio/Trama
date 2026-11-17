# Verifica di Trama 0.71.0 beta

La verifica riguarda i casi e gli ambienti riportati sotto. Il software resta in fase beta: alcune funzioni sono incomplete e questa evidenza non costituisce una validazione universale o clinica.

| Verifica | Esito |
| --- | --- |
| Suite Linux con Tk e Xvfb 1024×768 | 1.802 test OK, nessuno saltato |
| Suite Windows x64 nella sessione desktop | 1.802 test OK, nessuno saltato |
| Percorso GUI completo Linux | PASS |
| Percorso completo del portabile Windows estratto | PASS |
| Windows reale 1024×768, scala 100% | Sette percorsi delle nuove analisi PASS |
| Windows reale 1920×1200, scala 125% | Fit globale, WLS e ANOVA PASS; 120 DPI, Segoe UI |
| Windows reale 1920×1200, scala 150% | Fit globale, WLS e ANOVA PASS; 144 DPI, Segoe UI |
| Ripristino del display | 1920×1200 e scala 100% verificati |

I sette percorsi sullo schermo piccolo coprono fit globali personalizzati, test lognormali, selezione PCA, stime della retta, regressione multipla pesata, diagnostica ANOVA e assunzioni delle varianze. Il percorso completo include le altre famiglie, progetto e ricette precedenti, modifica ed esclusione di dati, ricalcolo, salvataggio e riapertura, uso dei risultati come nuovi dati ed export.

La GUI è pilotata attraverso i widget reali. Le scale 125/150% sono impostazioni del sistema Windows: l'applicazione registra DPI della propria finestra, dimensioni del display, font e fattore di scala. Il controllo dei DPI riguarda avvii separati alle tre scale. Il passaggio fra monitor a DPI diversi durante la stessa esecuzione non è stato provato.

I [risultati sintetici leggibili da programma](validation-071.json) mantengono i metadati dei casi nativi. I controlli numerici usano anche riferimenti indipendenti e casi limite di scala, precisione e degenerazione. Le attese Q–Q mantengono la provenienza di ogni residuo; i confronti di Spearman non impongono l'ordine di pareggi separati dall'arrotondamento di BLAS fra piattaforme.

Dopo le suite, la sola modifica al sorgente compilato riguarda il nome dei PNG del collaudo lognormale su schermi grandi. È stata provata nella VM; il portabile è stato ricostruito e il percorso completo ripetuto. L'archivio distribuito è lo stesso ZIP del portabile collaudato: non è stato ricostruito dopo l'accettazione. La documentazione aggiuntiva di verifica è pubblicata nel repository.

L'interfaccia italiana comprende il catalogo di analisi e i principali campi, scelte e messaggi. Alcuni fogli di risultati ed editor specialistici conservano testi inglesi. Le ricette rimangono canoniche cambiando lingua; nomi e contenuti dell'utente restano letterali.

