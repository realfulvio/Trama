# Qt Progetti 0.95 — punto di ripresa (lavoro in corso)

Pacchetto: Trama-Claude-02-Progetti-Qt-095 (copia completa in
/mnt/project-files/qt-progetti-095/ del progetto). Base main 7a7340c.
Ramo: claude/project-thread-hz1cm2. Nessuna riga di codice ancora: fermo
alle 17:26 (ora di Roma) del 2026-11-19 su richiesta di Luca.

## Fatto
- Letti README e SPECIFICA; fixture sessione-a/b copiate in tests/data/qt_projects/.

## Da fare, in ordine (dalla SPECIFICA)
1. Modulo piccolo `trama_qt/sessions.py`: elenco di schede, ognuna col suo
   `Project`, selezione, navigatore, layout, stato Ispettore/Info; transizioni
   con test (apri, duplicato per percorso canonico, riuso scheda vuota iniziale).
2. `QTabBar` objectName=projectTabs in `trama_qt/window.py`; azione
   `window.actions["close_project"]`; Nuovo/Apri in nuova scheda; Ctrl+Tab /
   Ctrl+Shift+Tab; etichette EN/IT con indicatore dirty e omonimi distinti.
   Punti: window.py:154 (self.project iniziale), 1626 new_project,
   1642 open_path, 1678 save, 1885 closeEvent. Riferimento Tk:
   tramastat.py:6429 switch_project, 6464 close_project.
3. Chiusura: Salva/Scarta/Annulla per scheda; closeEvent raccoglie le decisioni
   prima di perdere schede; Salva con nome non sovrascrive un progetto aperto
   in altra scheda.
4. Concorrenza: job attivo blocca cambio/apertura/chiusura (Annulla resta
   raggiungibile); nessun dato o risultato scambiato tra schede.
5. Test (GUI esterno + percorso invalido, dati con app occupata, cancellazione
   worker, salvataggio fallito, bozza Ispettore, chiusura con due schede dirty),
   smoke con due progetti, misura switch 10.000×30, schermate EN/IT su due
   risoluzioni, verify.py del pacchetto, PR draft verso main.
