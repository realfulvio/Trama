# Sviluppo e verifiche

[Presentazione](../README.md) · [Archivio delle funzionalità](release-history.md)

Trama usa Python, PySide6/Qt e librerie scientifiche open source. La distribuzione Windows include il runtime; per sviluppare dal sorgente serve invece un ambiente Python compatibile con le dipendenze fissate.

## Ambiente di sviluppo

Su Windows con Python 3.13:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m trama_qt
```

Per i test GUI headless configura un display di almeno **1024×768**; una risoluzione inferiore non è un collaudo valido della disposizione dei dialoghi.

## Verifiche

```sh
python -m unittest discover -s tests -p 'test_qt_*.py'
python tests/legacy_reference.py
python -m trama_qt --smoke CARTELLA
```

Il confronto con campioni esterni richiede i relativi file: la loro assenza non vale come confronto superato. Le fixture sintetiche incluse e le prove di regressione non certificano l'equivalenza universale con un altro programma.

Per uno smoke isolato usa una directory di preferenze dedicata (`APPDATA` su Windows, `HOME` su Linux) e una cartella `MPLCONFIGDIR` separata. Le prove non devono alterare progetti o configurazioni dell'utente.

## Pacchetto Windows

```powershell
.\build.ps1
```

Il processo crea un pacchetto portabile con l'eseguibile e le dipendenze. `package_windows.py` include la licenza del progetto e raccoglie le licenze delle dipendenze in **Third-party licenses**. Una modifica al marchio nel sorgente compare negli eseguibili solo dopo una nuova compilazione; non cambia i file già pubblicati.

Prima di distribuire una build verifica test, avvio del portabile estratto, flussi GUI pertinenti, salvataggio e riapertura, export e corrispondenza fra sorgente e archivio. I digest pubblicati servono a controllare l'integrità del download, non sono una certificazione del software.

Per contributi e segnalazioni usa gli strumenti del repository, senza allegare dati riservati, credenziali o documenti di terzi non redistribuibili. Consulta [licenza e diritti](legal.md) e [crediti](../THIRD_PARTY_NOTICES.md).

## Compatibilità dopo la rinomina

Il prodotto e i nuovi pacchetti si chiamano **Trama**. Il formato `.alab`, i nomi tecnici delle preferenze e il protocollo degli appunti conservano i loro identificatori storici. Il codice Tk è archiviato in `tramastat.py` con i relativi test storici. Le release fino alla 0.70.0 mantengono i nomi originali dei loro archivi ed eseguibili.

