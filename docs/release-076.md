# Trama 0.76.0 beta

L'avvio normale mostra subito il logo Trama con un cerchio animato. L'indicatore
resta in movimento durante il caricamento dei moduli e si chiude quando la
finestra principale è pronta, senza una durata minima imposta. La lingua segue
la preferenza dell'interfaccia. [Schermata di avvio](startup-screen.md).

**Fit custom equation → Output → Parameter intervals** offre ora anche
**Profile likelihood**, usando il livello di confidenza già selezionato.

- Coefficienti fissi, vincoli e SD relative vengono rispettati durante la
  ristima degli altri coefficienti liberi.
- Il foglio **Parameter CI status** distingue radici del profilo, vincoli
  raggiunti, coefficienti fissi e limiti non disponibili con motivo.
- I coefficienti su un vincolo possono avere un profilo unilaterale anche
  quando il loro SE Wald non è disponibile.
- Il calcolo è annullabile e conserva l'ultimo risultato completato. Le
  ricette Wald precedenti mantengono i quattro fogli e i valori originari.

I profili sono locali, approssimati e condizionati alle SD relative inserite;
non enumerano tutti i rami disgiunti e non propagano l'incertezza delle SD.
Restano i limiti di lavoro espliciti descritti nella guida. Tutte le versioni
0.x rimangono beta.

[Guida ai profili personalizzati](custom-parameter-profiles.md) ·
[Verifiche e limiti](validation-076.md)
