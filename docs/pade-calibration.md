# Calibrazione razionale di Padé (1,1)

Il modello **Padé (1,1)** estende il comando **Interpola una curva di calibrazione** (`Interpolate a standard curve`) con una funzione razionale semplice, adatta a risposte che si incurvano progressivamente o si avvicinano a un plateau nell’intervallo degli standard. È disponibile nelle direzioni **X da Y** (`X from Y`) e **Y da X** (`Y from X`) con `Curve = Nonlinear` e `Model = Padé (1,1)`.

## Modello ed equazione in *z*

Per preservare la stabilità numerica anche su ascisse traslate o di ordine di grandezza elevato, gli standard vengono prima normalizzati nell’intervallo chiuso $[0, 1]$:

$$z = \frac{X - X_{\min}}{X_{\max} - X_{\min}}, \qquad X \in [X_{\min}, X_{\max}]$$

La curva stimata è:

$$Y(z) = \frac{A_0 + A_1 \cdot z}{1 + B_1 \cdot z}$$

I coefficienti riportati nel foglio `Calibration parameters` (`A0`, `A1`, `B1`) sono riferiti alla variabile normalizzata $z$, non direttamente a $X$. L’origine $X_{\min}$ e la scala $X_{\max} - X_{\min}$ della normalizzazione sono riportate nel foglio `Fit diagnostics`.

### Esempio numerico

Supponiamo di avere standard con $X \in [10, 30]$ ($X_{\min} = 10$, scala $X_{\max} - X_{\min} = 20$) e stima:

- $A_0 = 2{,}0$
- $A_1 = 12{,}0$
- $B_1 = 2{,}0$

1. **Previsione diretta (`Y from X`)** per $X = 17{,}5$:
   $$z = \frac{17{,}5 - 10}{20} = 0{,}375$$
   $$Y = \frac{2{,}0 + 12{,}0 \cdot 0{,}375}{1 + 2{,}0 \cdot 0{,}375} = \frac{6{,}5}{1{,}75} \approx 3{,}714286$$
   Agli estremi dell’intervallo: per $X = 10$ ($z = 0$) si ha $Y = A_0 = 2{,}0$; per $X = 30$ ($z = 1$) si ha $Y = (2{,}0 + 12{,}0)/(1 + 2{,}0) = 14/3 \approx 4{,}666667$.

2. **Calibrazione inversa (`X from Y`)** per una risposta incognita $Y = 4{,}0$:
   $$z = \frac{Y - A_0}{A_1 - Y \cdot B_1} = \frac{4{,}0 - 2{,}0}{12{,}0 - 4{,}0 \cdot 2{,}0} = \frac{2{,}0}{4{,}0} = 0{,}5$$
   $$X = X_{\min} + (X_{\max} - X_{\min}) \cdot z = 10 + 20 \cdot 0{,}5 = 20{,}0$$

Se le ascisse vengono traslate di $10^9$ ($X \in [1\,000\,000\,010;\; 1\,000\,000\,030]$), la variabile $z$ e i coefficienti $(A_0, A_1, B_1)$ rimangono invariati; in `Fit diagnostics` cambia soltanto `X origin (X min)`.

## Stima, vincolo sul denominatore e requisiti

- **Standard**: vengono usate tutte le coppie $(X, Y)$ finite; le coppie incomplete vengono ignorate e le repliche rimangono osservazioni separate. Le colonne delle richieste non partecipano alla stima.
- **Requisiti minimi**: almeno **4 osservazioni** e **3 valori distinti di $X$** con $X_{\max} > X_{\min}$ (altrimenti errore sul campo `X`), e risposta $Y$ non costante (altrimenti errore sul campo `Y`).
- **Obiettivo**: minimi quadrati ordinari non pesati dei residui **in $Y$**, $\sum_i (Y_i - \hat{Y}(z_i))^2$.
- **Assenza di poli**: il denominatore $1 + B_1 z$ è vincolato a restare almeno $10^{-6}$ su tutto $[0, 1]$. Poiché è affine e vale $1$ in $z = 0$, il vincolo equivale a $1 + B_1 \ge 10^{-6}$ e il denominatore minimo nell’intervallo è $\min(1, 1 + B_1)$.
- **Ottimizzazione**: proiezione variabile 1D su $u = \ln(1 + B_1)$ (con soluzione lineare esatta per $(A_0, A_1)$ tramite Gram–Schmidt modificato, griglia logaritmica su $1 + B_1 \ge 10^{-6}$, inizializzazione linearizzata e $B_1 = 0$, raffinamento scalare vincolato) seguita da raffinamento locale ai minimi quadrati vincolati (TRF con Jacobiano analitico).

## Direzioni, identificabilità e stime puntuali

- **Y da X (`Calibrated predictions`)**: restituisce `Predicted Y` solo nell’intervallo chiuso $[X_{\min}, X_{\max}]$ (`In range`); le richieste esterne mantengono valore vuoto con stato `Outside calibration`. I limiti `Y lower` e `Y upper` restano vuoti.
- **X da Y (`Interpolated values`)**: poiché $1 + B_1 z > 0$ su $[0, 1]$, la derivata $(A_1 - A_0 B_1)/(1 + B_1 z)^2$ non cambia mai segno e la curva è monotona (crescente o decrescente). L’inversione è considerata identificabile quando l’escursione $|Y(1) - Y(0)|$ supera la tolleranza relativa alla scala della risposta $\max(10^{-8} \cdot \text{scala},\; 10^{-12})$ e $|A_1 - A_0 B_1| > 10^{-12} (|A_1| + |A_0 B_1|)$.
  - Richieste nell’immagine della curva (compresi gli estremi esatti o equivalenti entro arrotondamento numerico): stato `In range`.
  - Richieste fuori dal codominio della curva: valore vuoto e stato `Out of range`.
  - Fit finito ma curva numericamente piatta: valore vuoto e stato `Not identifiable`.
- **Solo stime puntuali**: in questa consegna `Padé (1,1)` non calcola bande né intervalli inversi (`Mean response` o `Prediction` vengono rifiutati con errore sul campo `Uncertainty`). Eventuali valori salvati e inattivi di `Confidence level (%)` e `Replicate count column` non hanno effetto quando `Uncertainty = None`. Nel dialogo Qt, passando da un modello con intervalli a `Padé (1,1)`, `Uncertainty` ritorna automaticamente a `None`.

## Risultati, grafico ed esportazioni

- `Calibration parameters`: righe `A0`, `A1`, `B1` con colonna `Estimate`.
- `Fit diagnostics`: modello, `N`, `Distinct X`, gradi di libertà residui `df`, `Residual SS (Y)`, `Residual SD`, `R²`, `X origin (X min)`, `X scale (X max - X min)` e `Minimum denominator`.
- **Grafico e progetto**: osservazioni degli standard, curva campionata su 300 punti finiti nell’intervallo $[X_{\min}, X_{\max}]$ e punti interpolati/previsti disponibili. Il progetto `.alab` si salva, riapre e ricalcola in Classica Qt con esportazione CSV e SVG vettoriale.
