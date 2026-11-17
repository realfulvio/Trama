# Profili dei parametri nel fit globale personalizzato

In **Regression and Curves → Global fit custom equation**, la pagina **Output**
offre **Parameter intervals → Profile likelihood**. Il livello è quello del campo
**Confidence level (%)** della stessa pagina. In italiano la scelta è
**Intervalli dei parametri → Profilo di verosimiglianza**.

Il valore predefinito **Symmetric (Wald)** conserva i risultati precedenti. Le
ricette salvate senza questa opzione continuano a usare quel percorso e non
acquisiscono la nuova chiave solo perché vengono aperte e confermate.

## Un unico obiettivo per tutte le serie

Il fit iniziale stima contemporaneamente i coefficienti di tutte le serie:
un parametro **Shared** occupa una sola coordinata; un parametro **Local** ne
occupa una per serie, salvo valori fissati individualmente. I coefficienti
**Fixed** e i valori fissati nella pagina **Series constraints** non vengono
ristimati. I vincoli di un coefficiente condiviso sono l'intersezione dei
vincoli dichiarati dalle serie.

Per ogni coordinata libera, il profilo mantiene un valore di prova e ristima
tutte le altre coordinate libere sullo stesso obiettivo congiunto. Ogni serie
contribuisce a ogni ristima; non vengono prima adattate curve indipendenti.
Con `N` osservazioni complete complessive e `p` coordinate libere, si usa
`df = N − p` e si cerca la soglia extra-SS:

`SS_profile = SS_min × (1 + F(level; 1, df)/df)`.

Le SD relative inserite, se presenti, rimangono fisse. Cambiare tutte le SD di
uno stesso fattore non modifica il profilo. Questo percorso stima una varianza
residua comune; non tratta le SD come varianze assolute note e non propaga la
loro incertezza.

## Risultati e annullamento

Il foglio **Parameters** mantiene stime, SE e stato del fit iniziale; cambia
solo le colonne **CI low** e **CI high**. **Parameter CI status** aggiunge
ambito, serie, coefficiente, livello, df, pesatura e stato di ciascun estremo:

| Stato | Significato |
| --- | --- |
| Profile root | È stata trovata la soglia di confidenza |
| Parameter bound | L'insieme connesso raggiunge un vincolo del parametro |
| Fixed | Il coefficiente è fissato e non ha un intervallo stimato |
| Unavailable | L'estremo non è stato determinato; è riportato un motivo |

Un parametro su un vincolo può avere un profilo unilaterale anche se il fit
conserva SE e covarianza Wald non disponibili. Un vincolo resta distinto da
una radice di confidenza. Un limite non determinato non viene sostituito da
un intervallo simmetrico.

**Covariance**, **Residuals**, **Curve**, le bande della risposta e le previsioni
mantengono il calcolo del fit iniziale. Il livello di **Response** è separato
dal livello dei parametri. Le bande e previsioni con incertezza conservano
le restrizioni del percorso precedente, incluso il requisito del fit non
pesato; scegliere i profili non estende quel diverso metodo di inferenza.

Il calcolo avviene sul worker. **Cancel** interrompe anche la ricerca dei
profili e conserva l'ultimo risultato completato quando si modifica uno
studio esistente. La scelta è salvata in forma canonica nel `.alab`, anche
con interfaccia italiana.

## Limiti del metodo

- Al massimo 32 coordinate libere e 5.000 osservazioni complete complessive
  per la richiesta di profili. I limiti del fit Wald restano quelli precedenti.
- Un budget comune di 20.000 valutazioni e 10 milioni di valori residui copre
  tutti i coefficienti e tutti gli estremi della richiesta.
- La ricerca segue la soluzione locale confermata e la componente connessa
  intorno a essa. Non enumera tutti i rami disgiunti.
- L'inferenza non lineare è approssimata, soprattutto con pochi dati o vincoli
  attivi. Una ricerca esaurita o non convergente resta esplicitamente non
  disponibile; non prova che il vero intervallo sia infinito.
- Le equazioni restano nel parser ristretto dell'applicazione: non eseguono
  codice Python. Non vengono aggiunti nuovi metodi di pesatura.

[Profili indipendenti delle equazioni personalizzate](custom-parameter-profiles.md) ·
[Funzionalità](features.md)
