# Trama 0.77.0 beta

**Global fit custom equation → Output → Parameter intervals** offre ora
**Profile likelihood** per i coefficienti del fit congiunto.

- Ogni coefficiente condiviso conta una sola volta; quelli locali restano
  distinti per serie. Tutte le serie contribuiscono a ogni ristima del profilo.
- Valori fissi e vincoli per serie sono rispettati, usando `df = N totale − p libero`.
- **Parameter CI status** distingue radici di confidenza, vincoli raggiunti,
  coefficienti fissi e limiti non determinati con motivo.
- Sono supportati fit senza pesi e con SD relative inserite. Il calcolo è
  annullabile e conserva l'ultimo risultato completato dello studio modificato.
- La scelta è tradotta EN/IT e rimane canonica nel progetto. Le ricette Wald
  precedenti mantengono le proprie tabelle e chiavi.

Stime, SE, covarianza, residui, curve e inferenza della risposta restano quelli
del fit iniziale. Il livello dei parametri è separato da quello delle bande;
le bande e previsioni con incertezza conservano le loro restrizioni precedenti.

La ricerca è locale e approssimata, non enumera tutti i rami disgiunti e mantiene
fisse le SD relative. Sono previsti limiti espliciti di lavoro e fino a 32
coordinate libere / 5.000 osservazioni complessive per i profili. Un limite non
determinato non viene sostituito da un intervallo simmetrico. Tutte le versioni
0.x rimangono beta.

[Guida e schermate Windows](global-custom-parameter-profiles.md) ·
[Verifiche e limiti](validation-077.md)
