# Algoritmi K-means

In **Raggruppamento k-means** e **Selezione del modello k-means** puoi scegliere **Lloyd** con inizializzazione K-means++ oppure **Hartigan–Wong**. Per Hartigan–Wong, il limite di iterazioni conta i giri di trasferimenti ottimali e rapidi. Il calcolo con seme usa fino a dieci partenze da osservazioni distinte. Fra le partenze convergenti conserva la soluzione con la somma dei quadrati interna più bassa.

Nel raggruppamento puoi fornire una riga iniziale per gruppo. Scrivi i numeri delle righe del foglio separati da virgole, partendo da 1. Ogni riga deve avere tutti i valori selezionati, e le righe devono individuare centri distinti. Il campo vuoto usa le partenze con seme. Con la standardizzazione, centri e somma dei quadrati sono riportati sulla scala di calcolo.

Nella selezione del numero di gruppi l'algoritmo e il limite scelti valgono anche per i campioni di riferimento Gap. Il consenso usa i fit calcolati in quella ricerca. Con una ricetta importata compatibile, Trama ripristina il seme, il limite di iterazioni e l'intervallo di k. Le partenze e i campioni Gap vengono generati da Trama. Due programmi possono ricavare partizioni diverse a parità di seme perché la sequenza di inizializzazione può essere diversa. Puoi consultare le viste originali archiviate dove disponibili.
