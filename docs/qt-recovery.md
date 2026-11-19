# Recupero progetti dopo una chiusura anomala (Qt)

*Recover projects after an abnormal exit — English summary at the end.*

Trama tiene una **copia di recupero** di ogni progetto aperto con modifiche confermate ma non ancora salvate. Se Trama si chiude male (crash, corrente che salta, processo terminato), al riavvio compare un avviso con il numero di copie disponibili e **File → Recupera progetti…** permette di riaprirle.

## Che cosa c'è nella copia

- Fogli dati, valori, esclusioni, formule, fogli Info, ricette delle analisi, stili dei grafici confermati, layout e legami tra analisi: tutto quello che Salva scrive nel file `.alab`.
- I risultati non sono copiati: si ricalcolano come dopo una normale apertura.
- **Non** ci sono: le bozze ancora aperte nell'Inspector o in un dialogo (finché non le confermi), la cella che stai ancora scrivendo, la cronologia Annulla/Ripeti, le preferenze.

## Quando viene presa

- Preferenza **Impostazioni → Copie di recupero…**: attiva di default, ogni **30 secondi** (si può scegliere 15, 30, 60 o 120).
- Le modifiche ravvicinate si raggruppano: la copia parte un intervallo dopo la prima modifica non ancora copiata, anche per le schede non attive. Se il progetto non cambia, non si riscrive nulla.
- La copia si prepara in un attimo sul thread dell'interfaccia (dati staccati, nessuna scrittura) e si scrive in sottofondo; Trama non aspetta il disco e non aspetta i ricalcoli in corso (la copia contiene la ricetta confermata e i dati attuali).
- La copia non cambia il progetto: il file originale, il nome e il pallino • delle modifiche restano come sono.
- Nella barra di stato: «Ultima copia di recupero 21:04:10». Se una scrittura fallisce (disco pieno, cartella in sola lettura) la scritta diventa «Copia di recupero non riuscita · ultima 21:04:10»: l'ultima copia buona resta, e il motivo compare una sola volta nella riga di stato, senza finestre ripetute.

## Quando sparisce

- **Salva** riuscito: spariscono le copie coperte da quel salvataggio; le modifiche successive avranno nuove copie.
- **Chiudi → Scarta**: spariscono le copie di quella scheda, le altre schede non cambiano.
- **Chiudi → Annulla** o **Salva con nome → Annulla**: non sparisce niente.
- Chiusura normale della finestra: dopo le scelte Salva/Scarta per ogni scheda non resta nessuna copia.

## Recuperare

1. All'avvio, se ci sono copie, sotto la barra comandi compare «Trama ha trovato N copie di recupero…» con **Recupera…** e **Più tardi**. Lo stesso dialogo si apre da **File → Recupera progetti…**.
2. Il dialogo mostra per ogni copia il titolo, l'ultima copia (ora locale), lo stato dell'originale (**Immutato**, **Cambiato sul disco**, **Assente**, **Sconosciuto**, oppure **Mai salvato**) e il percorso dell'originale. Se l'originale è cambiato o sparito, un avviso nello stesso dialogo lo dice.
3. **Recupera** apre le copie scelte, ognuna nella sua scheda, come progetto *nuovo, modificato e mai salvato*, con il titolo «nome (recuperato)». Salva propone «nome (recuperato).alab» nella cartella dell'originale. L'originale sul disco non viene mai toccato e si può aprire nella sua scheda accanto alla copia.
4. **Più tardi** lascia tutto com'è; le copie restano nel dialogo.
5. **Elimina…** cancella le copie scelte dopo una domanda esplicita. Le copie rovinate (indice o file alterati) sono elencate a parte con il motivo e si eliminano con **Elimina non recuperabili…**; non impediscono il recupero delle altre.
6. Con 6 schede aperte (il massimo) Trama recupera finché c'è posto e lascia le altre copie intatte, con un messaggio.

Una copia recuperata resta protetta finché non la salvi o la scarti: se Trama si chiude di nuovo male, la copia è ancora nell'elenco (con le modifiche fatte dopo il recupero, se erano già state copiate).

## Limiti

- Al massimo **20 copie** (nuove copie oltre il limite si fermano), **64 MiB** per copia e **300 MiB** in tutto. Al limite Trama **sospende** le nuove copie e lo dice nella barra di stato; non cancella mai copie vecchie per fare spazio. Lo spazio si libera dal dialogo.
- Il formato `.alab` ha già un suo limite di 32 MiB per progetto: un progetto che Salva non accetterebbe non può avere una copia.

## Dove stanno i file

Nella cartella del profilo, la stessa di `preferences.json`, sottocartella `recovery`:

- Windows: `%APPDATA%\TramaStat\recovery`
- Linux: `$XDG_CONFIG_HOME/tramastat/recovery` (di solito `~/.config/tramastat/recovery`)

Nessun servizio, avvio automatico o cartella di sistema. I nomi dei file sono identificativi casuali, mai titoli o percorsi.

## Più finestre di Trama

Ogni finestra ha un'identità casuale e un *lease* (`recovery/leases/<id>.lease`) che rinnova ogni 20 secondi e cancella quando si chiude normalmente. Una finestra è viva se il suo lease è stato rinnovato da meno di 90 secondi; sullo stesso computer conta anche il PID, così un crash si riconosce subito. Un processo nuovo che riceve per caso il PID di uno morto ha un'altra identità, quindi non eredita niente. Una seconda finestra non offre né cancella le copie di un'altra finestra ancora aperta (il dialogo dice solo quante sono) e due finestre non possono prendere la stessa copia orfana: il passaggio di proprietà avviene sotto un file di lock esclusivo.

## Per sviluppatori

- `trama_qt/recovery_store.py` (senza Qt): `RecoveryStore(root)` con `write_snapshot`, `list_snapshots`, `problems`, `scan`, `read_snapshot`, `discard`, `claim`, `sweep`, `usage`; `Leases`; preferenze `load_settings`/`save_settings`. Schema 1: `<key>.json` (riferimento con generazione, dimensione, SHA-256, titolo, origine, stato dell'originale, proprietario, ora) e `<key>.<gen>.alab` (progetto completo).
- Ordine di commit: prima il payload (file temporaneo, fsync, rename), poi il riferimento (temporaneo, fsync, `os.replace` nella stessa cartella), poi la rimozione del payload precedente. Interruzione fra i due passi: resta valida la copia precedente; il payload nuovo è orfano e viene rimosso dopo un'ora. Disco pieno o cartella bloccata: `OSError` prima di sostituire qualsiasi cosa. Payload mancante o con dimensione/SHA diversi: copia non recuperabile, isolata dalle altre.
- `trama_qt/recovery.py`: `RecoveryController` (pianificazione, coda seriale, generazioni, stato), `RecoveryDialog`, `RecoverySettingsDialog`. Agganci in `window.py`: costruttore (`MainWindow(recovery=…)`, `None` nei test e negli smoke), `save`, `close_project`, `_put_project`, `closeEvent`, `place_project`, `recover_projects`, `recovery_settings`.
- `Project` (`trama_qt/project.py`) ha `revision` (cresce a ogni `dirty = True`), `recovery_key`, `recovery_generation` e `snapshot()`, che copia lo stato confermato senza toccare `path` e `dirty`. `analisi.data.project_bytes` serializza come `save_project`.
- Misure (`python tests/perf_qt_recovery.py`, container Linux, due schede 10.000×30): cattura sul thread GUI circa 2 ms per scheda; durante la scrittura in sottofondo (circa 0,4 s e 5,8 MB per copia) la GUI non si ferma mai più di circa 22 ms, perché le righe sono codificate a blocchi (`Snapshot.to_bytes`: stessi byte di Salva, ma senza una singola chiamata `json.dumps` che tiene il lock dell'interprete per 100 ms); con dati fermi per due intervalli, nessuna riscrittura.
- Prove: `tests/test_recovery_store.py`, `tests/test_qt_recovery.py`, `python -m trama_qt.recovery_drill CARTELLA` (crash reale di un processo separato), `python tests/perf_qt_recovery.py`.

---

## English summary

Trama keeps a recovery copy of every open project with confirmed but unsaved changes (Settings → Recovery copies…, on by default, every 30 s; 15/30/60/120). After an abnormal exit a notice at start-up and **File → Recover projects…** list the copies with their last time, the state of the original (unchanged, changed on disk, missing, unknown, never saved) and let you Recover (opens as a new unsaved project, "name (recovered)"; the original is never touched), leave for Later, or Delete with a confirmation. Damaged copies are listed apart and never block the others. Saves remove the copies they covered, Close → Discard removes that tab's copies, Cancel keeps everything. Limits: 20 copies, 64 MiB each, 300 MiB in total; at the limit new copies pause and nothing is deleted. Files live in the profile folder beside `preferences.json`, subfolder `recovery`. Undo history and drafts still open in a dialog are not part of a copy.
