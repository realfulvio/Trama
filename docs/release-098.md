# Trama 0.98.0 beta

Estrai il portabile Windows x64. **Trama.exe** e **Trama - Tk.cmd** aprono
l’interfaccia Classica. **Trama - Qt.cmd** apre l’interfaccia PySide6/Qt.
I due avvii usano lo stesso motore statistico e lo stesso formato di progetto.

- **Dendrogrammi e K-means.** L’[ordinamento ottimale delle foglie](leaf-ordering.md)
  è disponibile per il clustering gerarchico. I grafici collegati delle
  ricette importate compatibili seguono le assegnazioni ricalcolate.
- **ANOVA a misure ripetute.** Alle opzioni di sfericità si aggiungono
  [Huynh–Feldt e Limite inferiore](rm-anova-sphericity.md).
- **Analisi in Qt.** La [correlazione intraclasse](icc.md) misura accordo o
  coerenza tra valutatori. La [curva precisione–richiamo](precision-recall.md)
  confronta punteggi esterni su campioni comuni, con bootstrap appaiato facoltativo.
- **Progetti importati.** I profili compatibili collegano alcuni grafici
  di sopravvivenza, curve, intervalli e fasce di controllo ai risultati correnti.
  La [guida ai formati](compatibility.md) descrive i sottotipi verificati.
