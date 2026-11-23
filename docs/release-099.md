# Trama 0.99.0 beta

**Trama.exe** apre la Classica in Tk. **Trama - Qt.cmd** apre la Classica in
PySide6/Qt. Entrambi leggono e salvano gli stessi progetti `.alab`. Il foglio
Qt ha l’anteprima del grafico, l’Ispettore e i comandi di copia e incolla della
Classica. [Guida agli avvii](qt-migration.md).

- **Clustering gerarchico.** Il grafico dei gruppi mostra le osservazioni
  nelle unità originali. Silhouette e Gap confrontano i tagli dello stesso
  albero. Le simulazioni Gap possono usare più processi. I grafici collegati
  si aggiornano quando cambiano i dati. [Guida](hierarchical-import.md).
- **Formule nei fogli.** Il tasto `=` apre l’editor, che permette di cercare
  funzioni e colonne. L’importazione conserva l’ordine delle colonne
  calcolate e i valori disponibili. [Guida alle formule](formula-windows.md).
- **Confronti e sopravvivenza.** I test t possono usare campioni in colonne
  separate. Il test t lognormale accetta dati raggruppati. I confronti
  Kaplan–Meier possono usare coppie prestabilite e controllare il tasso
  di false scoperte. [Funzionalità](features.md).
- **Analisi nella Classica.** Sono disponibili anche in Tk la correlazione
  intraclasse, la curva precisione–richiamo, i contrasti ANOVA pianificati,
  la stabilità K-means, la validazione logistica e le operazioni di
  unione e rimodellamento dei fogli.
- **Progetti importati.** I file compatibili riaprono il foglio attivo
  salvato e mantengono più collegamenti fra dati, analisi, grafici e
  layout. I progetti con metadati di importazione vengono salvati in
  formato `.alab` 4 e richiedono Trama 0.99 o successiva per essere riaperti.
  [Formati supportati](compatibility.md).

Trama è in beta. Le guide descrivono i formati e i casi verificati.
