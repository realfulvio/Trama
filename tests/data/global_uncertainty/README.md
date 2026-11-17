# Fixture sintetiche e risultati attesi

Tutti i dati sono stati creati per questo incarico. Nessun file contiene osservazioni reali, dati di pazienti, credenziali o risorse estratte da programmi altrui.

## Come leggerle

Ogni caso ha un JSON di righe e un CSV equivalente per consultazione. **Il JSON è autorevole**: usa `pd.DataFrame(json.loads(...))`. In particolare `''` è un gruppo testuale valido e `null` è mancante. La lettura CSV standard tende a perdere questa differenza.

`recipes.json` contiene le opzioni già valide sulla base 0.70.0, senza le nuove opzioni. `verify.py:options` mostra le opzioni nuove aggiunte alle prove. Le ricette base usano 21 punti per serie; il minimo ammesso dal prodotto è 20.

Le colonne X / Y / Group / SD alimentano il fit. Query X / Query group / Query k sono colonne indipendenti nello stesso foglio e non devono aggiungere osservazioni al fit. Le righe possono contenere solo dati per query o solo dati per fit.

## Casi inclusi

| Caso | Che cosa mette alla prova |
| --- | --- |
| linear-shared | Un'unica pendenza B condivisa e due intercette A locali; correlazioni non nulle in C; nove query con duplicati e mancanti |
| linear-fixed | Intercetta di B fissata a 3.6 tramite Series constraints; le altre coordinate restano libere |
| linear-weighted | Stesso problema con SD relative; soltanto query puntuali ammesse dal nuovo perimetro |
| linear-weighted-scaled-sd | Tutte le SD ×1e8; risultati fisici invarianti |
| linear-small-y | Tutte le Y e le scale iniziali dei coefficienti ×1e−12; non è un fit perfetto |
| linear-empty-label | Gruppi `''` e `'A'`, con null presenti nelle query; non confondere il primo con null |
| decay-shared | A locale, K condiviso, C fissato a zero, con formula `A*exp(-K*X)+C` |
| decay-large-x | Stesso decadimento, X×1e12 e K÷1e12; curve e incertezza della risposta invarianti |
| linear-perfect | Residui numericamente nulli; stima conservata ma intervalli non disponibili secondo la politica esistente |
| all-fixed | Tutti i coefficienti fissati; nessuna coordinata libera né intervallo inventato |
| active-bound | Pendenza condivisa bloccata sul limite superiore; inferenza non disponibile |
| rational-domain | Formula `A/(1+B*X)`; query X=-1 singolare, X=-0.5 estrapolata valida e X=1 interna valida |

## Origine dei numeri

`expected.json` contiene otto insiemi di oracoli numerici: i sei casi lineari e i due decadimenti. Gli altri quattro casi hanno esiti e proprietà da verificare, non valori di intervallo da inventare.

Per i casi lineari `reference/oracle.py` risolve le equazioni normali con `fractions.Fraction`, senza chiamare il motore di Trama. Per linear-shared:

```text
[A_serieA, A_serieB, B_condiviso] = [49/50, 91/25, 127/100]
N = 9, P = 3, df = 6
RSS = 491/1000
```

Nel JSON ogni caso lineare conserva anche le frazioni esatte del problema. L'ordine dei parametri dell'oracolo è documentato in `coords`: non imporlo al motore di produzione, che ordina prima le coordinate Shared. Propagare la C con un ordine diverso dal gradiente darebbe un risultato sbagliato.

Per il decadimento l'oracolo usa un problema indipendente con Jacobiano analitico, Levenberg–Marquardt e trasformazione esplicita delle unità. Non importa codice di Trama. I quantili t sono quelli di SciPy. Le bande sono approssimazioni puntuali di Wald, non intervalli esatti non lineari.

I risultati attesi includono stime, C già scalata, RSS, df, griglia e query con limiti Confidence e Prediction. Per le query con Status=Outside domain i numeri matematici sono conservati come riferimento per Allow extrapolation=true: con l'opzione false il candidato deve invece restituire celle mancanti, come controlla il verifier. Il livello numerico degli oracoli è 90%, distinto dal livello 95% dei coefficienti nella vecchia ricetta. k riguarda solo la Prediction delle query.

Tolleranze del confronto candidato: normalmente `rtol=3e-6`, senza una tolleranza assoluta che nasconda le Y piccolissime. I test degli oracoli sono più stretti. Se una nuova piattaforma richiede una tolleranza diversa, dimostra il motivo e controlla l'errore rispetto alla scala; non sostituire gli expected.

## Compatibilità reale

`legacy-snapshot.json` è stato prodotto con il dispatcher della base verificata, per tutti e dodici i casi, prima di implementare la nuova funzione. Contiene gli schemi e le celle dei cinque fogli, gli assi e le legende.

`legacy-global-070.alab` è un progetto salvato dal codice della base: tabella sintetica linear-shared e sola ricetta globale storica, senza le nuove chiavi. Usalo nel collaudo di riapertura e compatibilità. Nessun indice pandas esterno speciale è promesso dal formato .alab.

Questi numeri sono **oracoli matematici indipendenti**, costruiti dai dati sintetici inclusi. Descrivono il contratto numerico di Trama; non sono risultati esportati da un'applicazione esterna.

Integration note0.71: legacy-global-070.alab was missing from the delivered branch (globally ignored extension). It is generated using the unchanged serializer at main222f1a45 (version0.70.0), with the synthetic linear-shared data/recipe and all new response options absent. It tests genuine legacy serialization rather than a current-format roundtrip.

