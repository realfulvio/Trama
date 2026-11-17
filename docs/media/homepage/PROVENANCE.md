# Provenienza delle immagini della homepage

L'aggiornamento del marchio a **Trama** è documentato nella [nota di rinomina](RENAME.md). I prompt originali riportati sotto conservano il nome storico.

## Aggiornamento 16 novembre 2026

- `modern-workspace-windows.png`: cattura reale del portabile Windows 0.73 beta, runtime `0083eb0` (codice applicativo invariato nel candidato finale). Lingua italiana, Segoe UI, 96 DPI; desktop 2560×1440, area client richiesta 1560×930. Dati sintetici XY con tre repliche per gruppo: il grafico dichiara la prima replica, senza media implicita. La finestra è catturata entro i suoi bordi, senza compositing o ridisegno.

- `modern-workspace-linux.png`: cattura dell'applicazione sul ramo `codex/modern-theme`, runtime `06871e8`, proposta #109. Linux/Tk 8.6 sotto Xvfb 1600×1000, finestra 1580×930 più menu. È un'anteprima in sviluppo: non è un collaudo Windows né la versione pubblicata. La griglia contiene tre repliche per ciascuna serie; il grafico mostra esplicitamente la prima replica di ciascuna, senza media implicita.
- `heatmap-standard-linux.png`: cattura dell'applicazione su main `b496cad`, Linux/Tk 8.6, stessa dimensione. Matrice sintetica 8×9, generatore PCG64 con seed 16112026, gradiente esplicito da −2 a 2. Le funzionalità di main possono precedere lo ZIP scaricabile.

Le due immagini sono catture del desktop limitate ai bordi della finestra, senza ridisegno, sovrapposizione di UI o ritocco dei risultati. Non contengono dati di laboratorio, percorsi locali o nomi di computer. La descrizione delle nuove schermate non sostituisce il collaudo nativo.

## Schermate Windows già pubblicate

Le tre immagini `worksheet-windows.png`, `graph-inspector-windows.png` e `layout-windows.png` sono catture della finestra nativa di Trama 0.71.0 beta su Windows 11, con la nuova UI A, lingua italiana, Segoe UI e ridimensionamento di sistema 100% (96 DPI, processo per-monitor aware). Lo schermo è 1920×1200; la finestra di lavoro è 1440×960. Le immagini sono catturate dal desktop sulla finestra visibile, senza ridisegno o ritocchi.

I dati sono sintetici e riproducibili (seed 240). Il fit globale legge le sei sottocolonne del foglio XY, usa le medie a ogni X e condivide il plateau fra le due serie. Il progetto è disponibile in [Laboratorio.alab](../../examples/Laboratorio.alab). Entrambi i grafici sono stati ricalcolati prima delle catture; queste immagini illustrano il prodotto, non costituiscono da sole validazione scientifica.

## Marchio e illustrazione

Il concept del logo e l'immagine di apertura sono stati generati con lo strumento integrato imagegen, senza CLI o API esterne. Il logo di produzione è ricostruito con percorsi SVG modificabili; PNG e ICO sono rasterizzazioni di quel vettoriale. Il logotipo usa glifi DejaVu Sans in tracciati, con [avvisi del font](../../../assets/brand/DejaVu-LICENSE.txt).

`hero.webp` è un'illustrazione promozionale, non un'interfaccia o un risultato scientifico. Il concept generato è stato usato come riferimento creativo del simbolo; nessun logo di terzi è stato usato come riferimento. Non è stata svolta una ricerca esaustiva dei marchi simili. Il formato WebP riduce il peso del banner; il contenuto dell'illustrazione non è stato ricomposto con schermate inventate.

## Prompt originali (nome precedente)

### logo

```text
Use case: logo-brand. Asset: final production app icon for TramaStat, an independent open-source scientific statistics and graphing application for Windows. Create ONE exceptional, distinctive compact symbol, no text, transparent background. A sculpted but flat vector-style ribbon monogram: a bold capital T formed by two interwoven teal ribbons, with a graceful ascending coral statistical curve integrated into the counterspace and one small coral data point. Make the T immediately readable, not a generic bar chart, not a flask, not a prism or triangle. Strong clean geometry, intentional negative space, precise optical balance, rounded terminals, limited palette deep midnight navy #102D3A, saturated teal #12A89D, pale mint #7DDED0 and restrained coral #F18A72. The colored mark may sit on a softly rounded midnight-navy square with generous inner padding, outside the square truly transparent. Premium restrained scientific software identity, excellent at 32 pixels, smooth clear contours, no fine grid, no tiny lines, no glossy 3D, no mockup, no shadows outside the icon, no lettering, no watermark, no variants or sheet. Centered single 1:1 icon, large high resolution.
```

### hero

```text
Use case: ads-marketing. Asset: polished GitHub product hero banner, panoramic landscape 2.4:1, for TramaStat scientific statistics software. The attached transparent wordmark is the approved brand reference: reproduce the same woven teal T symbol and the exact name TramaStat, without redesigning it. Sophisticated editorial layout on deep midnight navy with restrained teal and warm coral. Left half: wordmark near the top, beautifully set LARGE exact Italian headline in ivory 'Dai dati alle figure.' on two balanced lines, and small exact subline 'Statistica e grafici scientifici. Open source.' Generous clear margins; all text razor sharp, high contrast and impeccably spaced. Right half: an elegant original abstract scientific illustration of three translucent stacked plotting planes with a few crisp data dots, one smooth fitted sigmoid, a pale confidence ribbon and coral error bars, subtle curved data ribbons weaving between them. Not a literal app screenshot, no invented UI, no buttons or window chrome. Clean and calm; no neon haze, lens flares, microscopic text, stock lab photo, competitor logos, fake testimonials, shields, certification badges or watermarks. Premium accessible software for research laboratories. Keep visual hierarchy obvious and text fully legible at GitHub content width. Finished production artwork, not a mockup board or variations.
```

### hero_revision

```text
Edit this finished TramaStat banner with ONE precise change: recolor only the word 'TramaStat' in the upper-left brand lockup from dark teal to the same warm ivory as the large headline, so the brand name is clearly readable against the navy background. Preserve its exact spelling, letterforms, placement and size. Preserve absolutely everything else: icon, large Italian headline, subline, background, graph illustration, layout and colors. No additional text or objects.
```

