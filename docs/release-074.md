# Trama 0.74.0 beta

Questa beta aggiunge gli intervalli di confidenza configurabili dei parametri in **Nonlinear regression**, nella nuova scheda **Confidence intervals**.

- Livello dei parametri indipendente da quello delle bande della curva.
- Wald simmetrico oppure profilo extra-SS asimmetrico per i fit indipendenti non pesati.
- Stima puntuale, SE e curva del fit confermato conservati.
- Stato e motivo per ciascun estremo: radice, vincolo del modello o limite non determinato.
- Calcolo sul worker con annullamento, budget condiviso fra risposte e gruppi e conservazione dell'ultimo risultato completato.
- Dialogo EN/IT e ricette canoniche salvate nel `.alab`.

Il valore predefinito Wald al 95% conserva i risultati delle ricette precedenti. Il profilo segue una soluzione locale, non enumera tutti i rami disgiunti e non supporta ancora la pesatura. Gli intervalli non lineari sono approssimati; le verifiche su dati sintetici non costituiscono validazione clinica o certificazione regolatoria.

Il Tema standard resta predefinito; non vengono introdotti nuovi temi in questa versione.

[Guida con schermate Windows](nonlinear-parameter-intervals.md) · [Verifiche e limiti](validation-074.md) · [Funzionalità](features.md)
