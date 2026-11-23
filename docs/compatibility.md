# Formati e compatibilità

[Presentazione](../README.md) · [Guida rapida](getting-started.md)

## Formati nativi e tabellari

| Formato | Uso |
| --- | --- |
| `.alab` | Progetto Trama: dati, formule, esclusioni, ricette, stili, layout e fogli Info. |
| CSV / TSV | Importazione di tabelle e scambio di dati; export dei risultati in CSV. |
| XLSX | Importazione di fogli Excel. Le formule e tutte le funzionalità di una cartella Excel non vengono convertite in ricette Trama. |
| SVG / PDF | Export di figure e layout. I layout nativi preservano i componenti vettoriali supportati; le immagini raster restano raster. |
| PNG / TIFF | Export di figure raster, con opzioni di dimensione e risoluzione. |

I progetti `.alab` delle versioni precedenti si aprono con tabelle, titoli e collegamenti salvati. Trama salva in formato `.alab` 4 i progetti con metadati di importazione. Un progetto che conserva un ordine delle categorie per una colonna viene salvato in formato 5. Per riaprire questi file serve una versione di Trama compatibile con il formato salvato.

## Progetti legacy PZFX, PZF e PZT

Trama legge strutture supportate di **PZFX**, progetti XML/ZIP compatibili e dei formati binari **PZF / PZT** verificati. L'estensione da sola non garantisce il recupero di ogni contenuto.

- **Dati:** recupero delle tabelle e dei metadati riconosciuti.
- **Analisi:** ripristino delle ricette supportate e conservazione di risultati archiviati dove riconosciuti. Un risultato archiviato non è una nuova analisi ricalcolabile. Nei progetti ZIP, le [ricette gerarchiche riconosciute](hierarchical-import.md) possono ripristinare clustering di righe e colonne, trasformazioni e report come analisi native modificabili. Le ricette PCA standardizzate compatibili recuperano analisi parallela, seme, rapporti e grafico dei punteggi con gruppi, anche da un risultato multivariabile archiviato. Il ricalcolo usa la presentazione e il generatore di Trama. Una ricetta compatibile di selezione K-means ripristina algoritmo, intervallo di k, seme e limite di iterazioni. Per i modelli verificati, conserva anche le partizioni e le statistiche Gap finché i dati e le impostazioni corrispondono a quelli originali. [Impostazioni K-means](kmeans-algorithms.md). Un'ANOVA multifattoriale ordinaria supportata riattiva le dimensioni dell'effetto e la soglia α quando il riepilogo salvato contiene i risultati completi per tutti i termini.
- **Grafici:** alcuni grafici verificati diventano modificabili; altri restano viste originali PDF/EMF. Colori, assi, annotazioni e geometria si conservano entro le capacità del singolo importatore. Nei grafici a dispersione multivariabili compatibili, Trama riapre le coordinate salvate con categorie, colori con opacità, dimensioni dei simboli e assi lineari. Le viste gerarchiche compatibili di righe e colonne seguono le assegnazioni del raggruppamento e mostrano i nomi delle osservazioni nel foglio delle coordinate. Le viste con livelli aggiuntivi possono richiedere un importatore diverso.
- **Trasformazione logaritmica di X:** nei progetti XML e ZIP compatibili, la trasformazione standard Log10 dell'intero foglio XY si riapre come **Trasforma concentrazioni (X)**. Si può modificare la sorgente e ricalcolare il logaritmo conservando le repliche Y e le celle mancanti. Le tabelle di risultato archiviate, quando presenti, sono consultabili accanto all'analisi ricalcolabile.
- **Normalizzazione e fit dose-risposta collegati:** nei progetti XML con il profilo riconosciuto, Trama usa il risultato di Log10(X) per normalizzare ogni replica al minimo e al massimo delle medie di riga della sua serie. Il fit logistico a due serie con estremi fissi 0 e 100 si apre in due analisi collegate, con Log EC50 separato e condiviso. I risultati, l'inferenza e i grafici nativi vengono ricalcolati con il motore di Trama.
- **Confronti di sopravvivenza:** le ricette Kaplan–Meier compatibili ripristinano Gehan–Breslow–Wilcoxon, il trend con l’ordine delle categorie salvato e i confronti log-rank contro un controllo con correzione di Holm–Šídák. Il trend e il controllo richiedono ruoli identificabili e categorie coerenti con le osservazioni incluse.
- **T-test appaiato:** per le ricette compatibili, il grafico di stima riprende le coppie complete, l’ordine delle categorie e l’intervallo al 95% della differenza media. Il grafico si aggiorna insieme al t-test quando cambiano i dati.
- **Intervalli dei confronti ANOVA:** se il progetto ZIP contiene un grafico degli intervalli riconosciuto, Trama lo collega alla tabella dei confronti multipli del modello ricalcolato. Gli estremi usano il metodo di confronto di Trama e si aggiornano dopo una modifica dei dati.
- **Osservazioni raggruppate ANOVA:** per i grafici compatibili, il fattore primario definisce le serie e le combinazioni degli altri fattori definiscono le categorie. Le repliche vengono ricostruite dalle osservazioni usate dal modello e il grafico si aggiorna insieme all'analisi.
- **Regressione non lineare multivariabile:** la ricetta compatibile di inibizione normalizzata a pendenza variabile recupera il livello degli intervalli di profilo. Se il progetto salvava la trasformazione log10(IC50) con limiti asimmetrici, Trama la ricalcola per ogni gruppo usando stima e limiti positivi del fit corrente. Nel grafico collegato compatibile, scala, limiti degli assi ed etichette salvate diventano impostazioni modificabili in Trama.
- **Grafici di sopravvivenza:** nei progetti ZIP con una sola variabile evento e la serie completa delle curve riconosciute, il grafico salvato si ricollega alla ricetta Kaplan–Meier. Conserva titolo e ordine delle serie e si aggiorna con i risultati quando modifichi i dati. Il grafico nativo traccia le barre di confidenza asimmetriche ai tempi con eventi e mostra i limiti numerici nella tabella della curva. Le opzioni della ricetta includono barre, banda puntuale o errore standard.
- **Punteggi PCA:** il grafico collegato con ellissi per gruppo riprende titolo, limiti lineari fissi, tacche principali e linee a zero puntinate nei progetti ZIP compatibili. Il recupero si applica alla coppia di componenti salvata.
- **Curve non lineari:** per i grafici compatibili con griglia lineare e limiti automatici, Trama collega osservazioni e curve al fit. Mantiene il numero di campioni della griglia e aggiorna gli estremi in base alle osservazioni incluse. I fogli salvati con le coordinate originali restano consultabili.
- **Intervalli X per regressione lineare e non lineare:** nella scheda **Intervalli X** scegli quali osservazioni entrano nel fit. I limiti sono inclusivi. I campi della curva controllano separatamente l'intervallo disegnato e il numero di campioni. Quando scegli una griglia, il foglio delle coordinate distingue i punti di estrapolazione. Lascia i campi vuoti per usare le impostazioni automatiche. Nel fit lineare puoi inoltre mostrare le osservazioni fuori intervallo senza includerle nella stima. Un profilo XML compatibile ripristina anche il grafico XY collegato ai dati grezzi. Le note testuali interne al grafico del fit sono recuperate come annotazioni modificabili.
- **Fit limitato di una risposta logaritmica nei PZT XML:** nel profilo a una serie verificato, Trama ripristina la trasformazione Log10 di Y e la regressione lineare che legge il suo risultato. Recupera i limiti X del fit e la griglia separata della curva. Il logaritmo di valori non positivi resta vuoto nel foglio trasformato.
- **ANOVA da risultati raggruppati:** nei progetti ZIP compatibili, un’ANOVA ordinaria a due fattori può restare collegata alla ricetta Extract and rearrange da cui dipende. Trama ricalcola la tabella Type III a partire dalle repliche attuali. Le impostazioni salvate senza misure ripetute, confronti post-hoc o diagnostica aggiuntiva sono quelle supportate dal collegamento.

  In Qt, apri **Estrai e riorganizza** e scegli la tabella risultante nella
  scheda **Variabili**. I campi seguono la scelta tra XY, Colonna, Raggruppata e
  Contingenza. Per una tabella raggruppata, indica la misura e i due fattori. Per
  una contingenza, indica trattamento ed esito e, facoltativamente, una colonna
  di conteggi. Nelle analisi già create, **Cambia parametri…** applica la nuova
  disposizione al risultato e ricalcola le analisi collegate. **Annulla** lascia
  in vigore l'ultima configurazione confermata.
- **Ricette di estrazione dai progetti ZIP:** le impostazioni riconosciute
  recuperano XY, Colonna, Raggruppata e Contingenza. Si conservano i ruoli
  delle colonne, la variabile dei conteggi e, quando definiti da una
  variabile, i titoli delle righe e i soggetti supportati. Le opzioni di
  abbinamento sconosciute mantengono il risultato archiviato, se presente.
- **Seleziona e trasforma nei progetti ZIP:** le ricette riconosciute
  conservano l’intervallo di righe, i confronti con una soglia, quelli
  fra due colonne numeriche e il filtro sui valori presenti. L’intervallo
  parte da 1 e include entrambi gli estremi. Puoi modificare i criteri
  dal dialogo Qt. Le viste archiviate supportate rimangono consultabili.
- **Modello ANOVA con termini scelti:** l'importazione di un'ANOVA multifattoriale ordinaria può conservare le singole interazioni salvate. La ricetta deve contenere un'intercetta, l'effetto principale di ogni fattore dichiarato e tutti gli effetti di ordine inferiore di ciascuna interazione. Sono supportate interazioni fino a tre fattori.
- **Barre d’errore XY nei progetti ZIP:** le viste compatibili recuperano SD e SEM memorizzati, distanze superiori e inferiori e limiti espliciti. Se è salvato un solo estremo, la barra termina sul punto dall’altro lato. Le distanze disponibili sono modificabili nelle coordinate salvate.
- **Limiti XY nei progetti binari:** per il sottotipo compatibile con limiti espliciti, la tabella recupera le subcolonne Centro, Superiore e Inferiore, conservando valori vuoti e limiti invertiti. Se punti e barre coincidono con la geometria salvata, la copia modificabile espone le distanze visibili sopra e sotto ogni punto. Un lato assente resta vuoto. Assi, annotazioni e banda ombreggiata mantengono la presentazione salvata. Quando la geometria corrisponde alle subcolonne del foglio XY originale, il grafico si aggiorna da quel foglio. I progetti già salvati con un foglio di coordinate dedicato continuano a usarlo.
- **Fascia XY collegata:** nei progetti binari in cui tabella, coordinate salvate e poligono della fascia coincidono, Trama aggiunge un grafico vettoriale nativo. Modifica i limiti nel foglio XY per aggiornare la fascia e gli estremi delle barre. Il grafico riprende la scala e i limiti degli assi. Le annotazioni originali si consultano nelle viste del disegno salvato.
- **Layout:** recupero di viste e pannelli nei sottotipi supportati. In Qt, **Modifica pannello…** cambia posizione e dimensioni nelle unità originali. **Modifica dati del pannello…** apre il foglio collegato e ogni modifica aggiorna la vista del layout. Non ogni pannello, oggetto o collegamento originale può essere convertito in elemento nativo.
- **Saturazione e Scatchard nei progetti XML:** nei progetti compatibili Trama ripristina il fit a un sito, la trasformazione Scatchard e il layout a due pannelli. Modificare le osservazioni aggiorna la curva e i punti. La retta riprende le intercette dal suo foglio indipendente. Il layout conserva dimensioni della pagina e posizioni dei pannelli. Le note di testo semplice del grafico mantengono testo e posizione. I valori scritti nella nota restano quelli originali quando ricalcoli il fit. Il carattere delle note viene adattato allo stile di Trama.
- **Intervallo del logEC50 nei PZT XML.** Nel grafico dose-risposta a pendenza fissa compatibile, la fascia riprende i limiti dell'intervallo dal fit corrente. Modificare o escludere un'osservazione aggiorna curva e fascia. Il legame resta nel progetto `.alab`. Il grafico usa gli assi nativi di Trama e la fascia compare quando entrambi i limiti sono finiti.
- **Curve dose-risposta nei PZT binari.** Per i fit riconosciuti a una serie, il grafico collegato usa il campionamento e i limiti salvati. Le osservazioni compaiono quando il grafico le richiama. Modificare il foglio ricalcola il fit, con la normalizzazione dove prevista, e aggiorna la curva. Il collegamento si conserva in `.alab` e la figura si esporta in SVG vettoriale. La vista archiviata resta disponibile.
- **Curve standard 4PL e 5PL nei PZT binari.** I profili a una serie con X in log10 si ricollegano al loro fit quando le serie del grafico corrispondono alle coordinate salvate. La vista modificabile riprende la griglia della curva e i limiti degli assi. Dal grafico di origine, **Apri grafico modificabile** consente di raggiungere il foglio dati e aggiornare la regressione.
- **Simulazioni 4PL e 5PL nei PZT binari.** Nei due profili a una serie con X in concentrazione, **Apri grafico modificabile** apre una vista nativa di **Traccia una funzione**. **Cambia parametri…** modifica i coefficienti e il foglio collegato contiene i valori X della griglia. Il punto a concentrazione zero è disponibile nella tabella e si omette dalla vista logaritmica.
- **Curve bifasiche in PZT precedenti.** Nei due profili a una serie con X in concentrazione o log10, l'importazione ripristina il collegamento al foglio selezionato e il grafico ricalcolabile. Sono mantenuti anche il referto e la curva salvati.
- **Dose-risposta a pendenza variabile nei PZT ZIP.** Per il profilo verificato dopo una trasformazione log10, Trama usa le repliche individuali e stima una curva indipendente per serie con intervalli di profilo. Il grafico collegato mostra le osservazioni, conserva i limiti degli assi supportati e campiona le curve fino al limite osservato di ogni serie. Modificare i dati ricalcola la catena, che resta collegata nel progetto `.alab`.
- **Fascia di controllo nei grafici a colonne PZT.** Nel profilo compatibile il grafico riprende media ± deviazione standard campionaria dal foglio di statistiche descrittive. Trama conserva i colori assegnati alle posizioni del foglio originale e usa simboli nativi. La relazione con il risultato resta nel progetto `.alab`.
- **Riepiloghi geometrici nei PZT ZIP.** Le ricette compatibili per colonne senza sottocolonne di repliche si riaprono in **Statistica descrittiva → Riepilogo geometrico**. Trama ricalcola numerosità, somma se richiesta, media e deviazione standard geometriche e l'intervallo di confidenza al livello salvato. L'intervallo è calcolato sui logaritmi e riportato sulla scala dei dati.
- **Simulazioni di legame competitivo nei PZT binari.** I profili a un sito con log Ki o log IC50 si aprono in **Traccia una funzione** quando i parametri e la griglia riproducono tutti i punti del disegno archiviato. Se il grafico conserva una configurazione diversa, Trama la mantiene distinta dalla tabella dei risultati salvati. L'originale resta consultabile e la nuova curva si aggiorna quando modifichi i parametri o le ascisse.
- **Competizione omologa con più serie.** Nei PZT binari compatibili, la simulazione riapre una griglia X comune con parametri modificabili per ciascuna serie. La legenda conserva le etichette salvate. La concentrazione usata nel calcolo viene dal coefficiente numerico di ciascuna serie.
- **Competizione a due siti e deplezione.** Trama conserva i fogli di risultato delle simulazioni PZT compatibili con griglia regolare. Le curve log Ki e log IC50 a due siti e la competizione a un sito con deplezione si aprono come funzioni modificabili quando serie, coefficienti e coordinate salvate concordano. Le voci di serie prive di punti restano fuori dalla nuova figura.
- **Fit globali nei PZT binari.** I profili verificati a due serie per la competizione
  allosterica e la deplezione recettoriale si ricalcolano dai fogli originali.
  Trama recupera i coefficienti condivisi e i valori fissi del profilo.
  Per la deplezione con X in concentrazione, la figura mantiene la griglia
  logaritmica e la tabella originale conserva le ascisse lineari.
  Le ricette e i collegamenti ai disegni salvati restano disponibili in `.alab`.
- **Spostamento EC50 di Gaddum–Schild.** Nei quattro profili PZT verificati,
  **Apri grafico modificabile** collega il fit globale alle cinque serie
  originali, comprese le risposte mancanti. Trama recupera la concentrazione
  fissa di ciascuna serie e la scelta tra pendenza di Schild stimata e fissata a 1.
  La vista originale conserva la freccia e la nota multilinea.
- **Cinetica di associazione nei PZT binari.** I due profili verificati
  con una o due concentrazioni riaprono il fit delle repliche originali.
  Con una concentrazione, Trama recupera la concentrazione e il tasso
  di dissociazione fissati. Con due, recupera le concentrazioni per serie
  e stima insieme i parametri condivisi. Il grafico mostra le curve
  con il campionamento e gli assi salvati. Il foglio originale resta raggiungibile.
- **Dissociazione a una fase nei PZT binari.** La simulazione verificata
  si riapre in **Traccia una funzione** con valore iniziale, fondo
  e tasso salvati. Il grafico usa i 200 punti del disegno. La tabella
  originale da 201 punti, le note e il foglio associato restano consultabili.
- **Saturazione a un sito nei PZT binari.** I profili verificati di legame
  specifico e totale si riaprono in **Traccia una funzione**. Il grafico
  usa i 150 punti del disegno salvato. La tabella originale da 151 punti
  resta consultabile con il suo campionamento.
- **Michaelis–Menten con kcat nei PZT binari.** Il profilo verificato riapre
  il fit dalla serie selezionata e recupera la concentrazione enzimatica
  fissata. Le altre serie restano disponibili nel foglio dati. La vista
  modificabile mantiene l'intervallo degli assi e la griglia del disegno.
- **Cinetica enzimatica sigmoide nei PZT binari.** La simulazione
  allosterica verificata riapre Vmax, K a metà risposta e pendenza di Hill
  in **Traccia una funzione**, con i 151 punti della griglia salvata.
- **Rette semilogaritmiche e log-log nei PZT binari.** I due profili
  verificati riaprono il modello e i fogli di origine in **Regressione non lineare**.
  Il grafico conserva gli assi, i 150 punti di curva e la visibilità delle serie.
- **Grafici a colonne con media geometrica nei PZT ZIP.** Nel profilo verificato con osservazioni individuali e intervallo di confidenza al 95%, Trama ricrea i punti e i limiti asimmetrici dal foglio dati. Conserva l'asse Y lineare o logaritmico e i limiti salvati. Il grafico usa lo stile nativo, si aggiorna quando cambiano i dati e resta modificabile dopo il salvataggio in `.alab`.
- **Curve teoriche senza fogli sorgente.** Nei PZT XML compatibili, Trama recupera i valori originali generati, la sequenza X, gli assi, i colori e le annotazioni supportate. Le annotazioni mantengono la posizione e il testo si ridimensiona quando lo spazio disponibile si riduce. I valori si aprono in un foglio XY modificabile e il grafico si aggiorna con il foglio. Le equazioni e i coefficienti originali restano consultabili come riferimento. Il ricalcolo usa il foglio, comprese le modifiche e le esclusioni confermate. I caratteri e alcune decorazioni possono avere una resa diversa dall'originale.
- **Esportazione vettoriale:** **Esporta** salva il disegno originale PDF o EMF quando è conservato nel progetto. Le copie modificabili EMF compatibili esportano i dati correnti. Per salvare un layout importato con le modifiche ai pannelli, usa **Esporta EMF corrente…**.
- **Dati importati modificabili:** nei sottotipi previsti è possibile modificare i dati delle viste recuperate conservandone la presentazione supportata. Questo non estende automaticamente l'editabilità a tutti i documenti.
- **Residui salvati in PZT:** quando le coordinate del grafico corrispondono alla tabella dei residui, Trama apre una copia modificabile a dispersione. Le modifiche aggiornano il grafico della copia. Per ricalcolare i residui dai dati di origine serve una ricetta di regressione compatibile. La figura e il foglio risultati originali restano consultabili.

Il supporto dei formati legacy è limitato ai contenuti verificati. Non è previsto un export universale verso questi formati. Mantieni l'originale e confronta dati, impostazioni e figure prima di usare una conversione in un lavoro importante.

I dettagli per famiglia e i casi verificati sono nella [documentazione tecnica](coverage.md). L'importazione di file di terzi richiede che tu abbia il diritto di accedere e usare quei file; la licenza MIT di Trama non concede diritti su contenuti o programmi di terzi.

Trama è un progetto indipendente in fase beta. Le funzionalità di importazione sono in evoluzione: vedi le [note legali](legal.md).

