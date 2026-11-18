# Fixture e riferimenti numerici

Tutti i soggetti e i gruppi sono sintetici.

- `cohorts.csv` contiene due coorti da sei, in ordine misto. La prima ha un evento e una censura a tempo 2. La seconda ha un evento a zero e il suo nome contiene un dollaro letterale. A orizzonte 6,5 le curve si incrociano. Le altezze dei gradini e le aree sono state confrontate anche con `statsmodels.duration.survfunc.SurvfuncRight`.
- `degenerate.csv` copre assenza di eventi, caduta terminale a zero e gruppo con tutti gli eventi a zero.
- `text-status.csv` contiene codici di stato letterali e tre righe incomplete, una per ciascuno dei ruoli obbligatori.
- `expected.json` congela il risultato di `tests/oracle.py`. L’oracolo usa conteggi ripetuti dei risk set e la covarianza completa dei rettangoli con aritmetica razionale. Il dispatcher deve perseguire la forma efficiente prevista dalla specifica.
- `legacy-km.json` congela report e coordinate delle curve Kaplan–Meier del commit 1182b69 per la fixture a due coorti.
