# Grafico a bolle multivariato

Il **Grafico a bolle** (`Bubble plot`) codifica sullo stesso foglio di lavoro fino a quattro variabili visive oltre alle coordinate **(X, Y)**:

1. **Dimensione (`Size mode`)**
   - **Da colonna (`From column`)**: l’area di ciascun simbolo è proporzionale al valore positivo della colonna (`area = Area massima × valore / massimo disegnato`). La legenda riporta sempre il nome della colonna e l’area massima in `pt²`. Le righe con dimensione zero, negativa (errore esplicito) o mancante restano escluse dal calcolo del massimo e dalla figura.
   - **Area fissa (`Fixed area`)**: tutti i punti validi usano la stessa superficie in `pt²`; è sufficiente una coppia valida `(X, Y)` senza richiedere la colonna Dimensione.

2. **Colore di riempimento (`Fill color`)**
   - **Per categoria (`By category`)**: usa i livelli della colonna `Gruppo` (o un colore uniforme predefinito se assente), con editor dei **Colori delle categorie** per singolo livello.
   - **Colore fisso (`Fixed color`)**: usa un colore unico configurabile (`Colore dei punti`).
   - **Scala continua (`Continuous scale`)**: mappa una colonna numerica su tavolozze sequenziali (*Viridis*, *Cividis*, *Blu*, *Magma*, *Grigi*) o divergenti (*Blu–rosso*, *Freddo–caldo*, *Viola–verde*).
     - **Inverti tavolozza (`Reverse palette`)**: inverte esattamente la posizione normalizzata (`1 − u`).
     - **Limiti automatici o manuali (`Automatic` / `Manual`)**: i limiti automatici vengono calcolati **solo sui punti effettivamente disegnati** con segnale finito; con limiti manuali i valori esterni vengono saturati al colore dell’estremo (`clamp`).
     - **Centro divergente (`Diverging midpoint`)**: imposta un centro interno (es. `25` tra `0` e `100`, che mappa `0 → 0`, `25 → 0.5`, `100 → 1`).
     - **Segnali costanti e mancanti**: se tutti i valori validi coincidono viene mostrato il colore centrale con un unico tick in legenda; i valori mancanti usano il `Colore dei valori mancanti` (se sono tutti mancanti i punti restano disegnati con legenda esplicativa).

3. **Forma dei simboli (`Shape mode`)**
   - **Forma fissa (`Fixed shape`)**: simbolo unico tra 14 marker disponibili.
   - **Per categoria (`By category`)**: assegna fino a **12 simboli distinti** in automatico (mostrando un avviso esplicito oltre i 12 livelli o in caso di ripetizioni). I livelli numerici e testuali omonimi (es. `1` numero e `"1"` testo) restano distinti tramite identità tipizzata e le assegnazioni restano legate ai livelli anche dopo riordino delle righe o riapertura del file `.alab`. Le celle mancanti ricevono il simbolo di ripiego configurabile (`Forma mancanti`).

4. **Controlli Qt, anteprima e zero ricalcolo**
   - Modifiche a tavolozze, limiti, centro divergente, colori, area massima/fissa, simboli per livello ed etichette sono accessibili dal pannello **Ispettore grafico**, da **Cambia → Simboli e codifica…** (`Ctrl+Shift+B`), dal pulsante sulla pagina grafico o da **Formato grafico…**.
   - Ogni anteprima è reversibile con **Annulla / Esc** e confermata con un singolo **Applica** annullabile in un solo passo (`Ctrl+Z`). Tutte le modifiche estetiche aggiornano la figura e le tabelle `Valori delle bolle` / `Impostazioni` **senza rieseguire le analisi statistiche del progetto**.

L’area fissa nel dialogo dell’analisi usa tutte le coppie X/Y valide. Nei comandi di formato ridimensiona i punti
già selezionati dalla ricetta. Usa **Cambia parametri** per includere anche le righe omesse per dimensione zero
o mancante. I progetti che usano una delle nuove impostazioni vengono salvati in formato ALAB 29. I progetti
con le impostazioni precedenti restano leggibili e conservano i valori dei risultati.
