# Indicazioni per chi sviluppa Trama (persone e agenti)

Trama è un programma scientifico usato in ambienti dove contano prima di tutto l'affidabilità e l'esperienza d'uso, poi l'estetica. L'interfaccia valida è la **Classica Qt** (`trama_qt/`). Il tema «Vetro» non si usa più e non va esteso. Ambiente, verifiche e pacchetto Windows: [docs/development.md](docs/development.md).

## Requisiti che non si toccano

- **Precisione.** A schermo si vedono tutte le cifre previste dal formato numerico della cella o del risultato. Non ridurre mai la precisione mostrata per estetica. Copia scrive sempre le cifre memorizzate (`plain_text`).
- **Comandi.** Nessun comando deve sparire dai menu. Una funzione nuova va aggiunta in `MENUS` (`trama_qt/classic_bar.py`). Se ha una barra, va anche in `GROUPS`.
- **Lingue.** Ogni testo visibile passa da `qt(...)` (`trama_qt/strings.py`) o da `tr(...)` e ha la versione inglese e quella italiana.

## Convenzioni dell'interfaccia Classica

- **Stile.** Piatto e squadrato: `border-radius: 0`, niente ombre decorative, gradienti o animazioni.
- **Colori.** Si usano solo i token di `trama_qt/theme.py` (`LIGHT`/`DARK`), mai colori scritti a mano nei widget. Un token nuovo va aggiunto in entrambi i dizionari.
- **Icone.** Le icone della barra e del navigatore si creano con `theme.classic_icon(nome, token)`. Quelle disattivate usano già `icon_off`. Nel navigatore il colore dipende dal tipo: `kind_data`, `kind_result`, `kind_graph`.
- **Avvisi.**
  - `QLabel#errorBanner` si usa solo per gli errori veri: un calcolo fallito o un file danneggiato.
  - `QLabel#infoBanner` si usa per spiegazioni e limiti, per esempio «perché questo comando non è disponibile».
- **Barra di stato.** I messaggi passano da `window.status(testo)`, che li evidenzia e dopo 6 s li riporta a «Pronto», salvo durante un calcolo. Non scrivere direttamente su `window.message`.
- **Azioni di pagina.** Si aggiungono con `Page.command(azione)`, che le disegna come pulsanti (`#pageAction`).
- **Dialoghi.**
  - Il pulsante predefinito deve essere quello che conferma (Applica oppure OK).
  - I `QPushButton` interni al modulo, come «Formato legenda…», vanno impostati con `setAutoDefault(False)`, così Invio in un campo non apre un altro dialogo.
  - Va controllato che il dialogo stia in 1024×768 (`fit_dialog`).
- **Tastiera.**
  - Ogni comando frequente ha una scorciatoia sull'azione (`_action(..., shortcut=...)`). La finestra **Scorciatoie da tastiera** (F1) la elenca da sola.
  - Il focus con Tab deve restare visibile: non togliere il bordo di `:focus` nei fogli di stile.
- **Tabelle dei risultati.** Le colonne numeriche, comprese quelle miste numeri/etichette, sono allineate a destra, intestazione compresa (`FrameModel`).
- **Barra strumenti stretta.** I gruppi escono e rientrano secondo `OVERFLOW_ORDER`. Un gruppo meno importante non deve mai restare visibile al posto di uno più importante.

## Verifiche per le modifiche all'interfaccia

- Aggiungi un test Qt (`tests/test_qt_*.py`, piattaforma `offscreen`) che fallisca senza la modifica.
- Su Windows prova a 100% e 150%, con Tab, F1 e Invio nei dialoghi toccati.
- Nelle note della PR scrivi cosa non hai potuto provare: per esempio la scala reale di sistema o mouse e tastiera nativi.
