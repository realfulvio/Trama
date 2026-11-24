# Trama 0.102.0 beta

**Trama - Qt.cmd** apre la Classica in PySide6/Qt. **Trama.exe** apre la
Classica in Tk. Le due modalità usano lo stesso formato di progetto `.alab`.

- **Curve importate.** I profili verificati per agonisti pieni e parziali,
  IC50 assoluta e dose-risposta asimmetrica 5PL si collegano ai dati e ai
  parametri modificabili. Nei profili con decadimento bifasico indeterminato
  K2 parte dal riferimento salvato come valore fisso.
- **Standard e incogniti.** Il fit Padé importato recupera gli standard, le
  righe senza X e il grafico collegato. Le tabelle archiviate restano leggibili.
- **Grafici senza anteprima.** I profili lineari-quadratici verificati si
  ricalcolano da dati e coefficienti. I grafici vuoti compatibili si aprono
  con assi modificabili.
- **Layout a griglia.** In Qt, i profili verificati con pannelli ricalcolabili
  aprono anche una copia modificabile. L'ordine dei pannelli, i collegamenti
  ai dati e l'esportazione PDF e SVG si conservano nel flusso di lavoro nativo.
- **Esportazione rapida in Qt.** Sui monitor larghi, il comando Esporta adatta il
  grafico al limite del formato e conserva le proporzioni.

[Formati e compatibilità](compatibility.md).
