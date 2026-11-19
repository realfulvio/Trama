# Crediti e componenti di terze parti

[Presentazione](README.md) · [Licenza Trama](LICENSE) · [Note legali](docs/legal.md)

Trama è il nuovo nome di TramaStat; gli avvisi di copyright storici sono conservati nella licenza.

Trama è sviluppato dai contributori del progetto e si basa sul lavoro della comunità scientifica e open source. I riferimenti seguenti identificano i componenti principali; **non sostituiscono i testi integrali di licenza e copyright**.

## Componenti software

| Componente | Ruolo | Riferimento alle licenze |
| --- | --- | --- |
| [Python](https://www.python.org/) | Runtime | [PSF e avvisi inclusi](https://docs.python.org/3/license.html) |
| [Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/) | Interfaccia desktop (dalla 0.95) | [LGPLv3, usata come libreria dinamica non modificata](https://doc.qt.io/qtforpython-6/licenses.html) |
| [Tcl/Tk](https://www.tcl-lang.org/) | Interfaccia classica (`--tk`) | [Licenza Tcl/Tk](https://www.tcl-lang.org/software/tcltk/license.html) |
| [NumPy](https://numpy.org/) | Calcolo numerico | [Licenze del progetto e dei componenti incorporati](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| [SciPy](https://scipy.org/) | Statistica e ottimizzazione | [Licenze BSD e componenti incorporati](https://github.com/scipy/scipy/blob/main/LICENSE.txt) |
| [pandas](https://pandas.pydata.org/) | Tabelle | [BSD-3-Clause](https://github.com/pandas-dev/pandas/blob/main/LICENSE) |
| [Matplotlib](https://matplotlib.org/) | Grafici e rendering | [Licenza Matplotlib e componenti](https://matplotlib.org/stable/project/license.html) |
| [statsmodels](https://www.statsmodels.org/) | Modelli statistici | [BSD-3-Clause](https://github.com/statsmodels/statsmodels/blob/main/LICENSE.txt) |
| [Patsy](https://patsy.readthedocs.io/) | Matrici del modello | [BSD a due clausole](https://github.com/pydata/patsy/blob/master/LICENSE.txt) |
| [openpyxl](https://openpyxl.readthedocs.io/) | Lettura XLSX | [MIT](https://pypi.org/project/openpyxl/) |
| [Pillow](https://python-pillow.github.io/) | Immagini | [MIT-CMU e avvisi delle dipendenze](https://pillow.readthedocs.io/en/stable/about.html#license) |
| [pypdfium2 / PDFium](https://github.com/pypdfium2-team/pypdfium2) | Viste PDF | [Apache-2.0 / BSD-3-Clause e licenze delle dipendenze](https://github.com/pypdfium2-team/pypdfium2/tree/main/LICENSES) |
| [PyInstaller](https://pyinstaller.org/) | Preparazione del portabile | [GPL con eccezione per i programmi distribuiti](https://pyinstaller.org/en/stable/license.html) |

Il pacchetto Windows raccoglie gli avvisi delle distribuzioni installate nella cartella **Third-party licenses**, compresi quelli del runtime Python. Alcuni componenti incorporano altre librerie con avvisi propri: va conservata l'intera cartella, non soltanto questa tabella. Versioni e dipendenze dirette sono fissate in [requirements.txt](requirements.txt); per una distribuzione specifica fanno riferimento i testi inclusi in quell'archivio.

## Metodi, campioni e strumenti

Metodi statistici, scelte implementative e fonti dei campioni sono documentati nella [copertura tecnica](docs/coverage.md) e nelle relative prove. I campioni esterni non diventano MIT perché letti da Trama. Le loro attribuzioni e licenze restano applicabili; dove i file non sono redistribuibili, il sorgente non ne concede una copia.

## Identità e presentazione

- **Nome e simbolo Trama:** identità del progetto. Il nuovo simbolo a T intrecciata è disponibile in [SVG](assets/trama.svg), [PNG](assets/brand/trama-icon-1024.png) e [ICO](assets/trama.ico), con logotipi chiari e scuri in `assets/brand/`. Gli asset originali del progetto seguono la MIT; ciò non attribuisce diritti sui marchi di terzi o approvazioni commerciali.
- **Grafica promozionale:** il concept del simbolo e l'illustrazione di apertura sono stati generati con assistenza AI; il simbolo di produzione è stato ricostruito in vettoriale. Le immagini promozionali sono illustrazioni, non schermate del software. [Provenienza e prompt](docs/media/homepage/PROVENANCE.md).
- **Schermate:** catture della vera interfaccia Windows di Trama su dati sintetici, con la nuova icona in anteprima. Non sono mockup o prove di validazione scientifica.
- **Font e icone dell'interfaccia Qt:** [Figtree](https://github.com/erikdkennedy/figtree) sotto SIL Open Font License 1.1 ([testo](assets/qt/fonts/OFL.txt)); icone [Lucide](https://lucide.dev/) sotto licenza ISC ([testo](assets/qt/icons/LICENSE-lucide.txt)), ricolorate a runtime.
- **Tipografia del logotipo:** glifi DejaVu Sans convertiti in tracciati; [licenza e avvisi del font](assets/brand/DejaVu-LICENSE.txt). La conversione in tracciati evita la necessità di installare il font per visualizzare il logo.
- I crediti e le licenze dei materiali multimediali restano distinti dalla licenza del codice. Questa distribuzione non include i precedenti archivi promozionali e le loro tracce audio.
