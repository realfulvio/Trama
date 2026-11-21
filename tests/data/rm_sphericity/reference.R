# Reference for tests/test_rm_sphericity_hf.py. Run from this folder: Rscript reference.R > effects.json
# (the "effects" object of reference-r.json). It needs only base R. For every effect of second-dataset.csv it prints
# F, df, the p values of the three corrections and the two epsilons, from stats::anova.mlm(test = "Spherical").
suppressWarnings(options(digits = 17))
d <- read.csv("second-dataset.csv")
wide <- function(data, within) {
  data$cell <- do.call(paste, c(data[within], sep = "|"))
  cells <- unique(data$cell[order(do.call(order, data[within]))])
  m <- sapply(cells, function(k) data$Value[data$cell == k][match(sort(unique(data$Subject)), data$Subject[data$cell == k])])
  list(Y = m, idata = do.call(rbind, lapply(strsplit(cells, "|", fixed = TRUE), function(x) as.data.frame(as.list(setNames(x, within))))))
}
effect <- function(Y, idata, M, X) {
  fit <- lm(Y ~ 1)
  ssd <- SSD(fit)
  res <- anova(fit, M = M, X = X, idata = idata, test = "Spherical")
  Tm <- stats:::Thin.row(stats:::Proj(model.matrix(M, idata)) - stats:::Proj(model.matrix(X, idata)))
  sph <- stats:::sphericity(ssd, T = Tm, M = M, X = X, idata = idata)
  tab <- as.data.frame(res)
  list(F = tab[1, "F"], numdf = tab[1, "num Df"], dendf = tab[1, "den Df"], p = tab[1, "Pr(>F)"],
       gg_p = tab[1, "G-G Pr"], hf_p = tab[1, "H-F Pr"],
       lb_p = pf(tab[1, "F"], 1, tab[1, "den Df"] / tab[1, "num Df"], lower.tail = FALSE), gg = sph$GG.eps, hf = sph$HF.eps, n = nrow(Y))
}
out <- list()
w <- wide(d, c("Time", "Dose")); idata <- w$idata; idata[] <- lapply(idata, factor)
out$Time <- effect(w$Y, idata, ~Time + Dose, ~Dose)
out$Dose <- effect(w$Y, idata, ~Time + Dose, ~Time)
out[["Time:Dose"]] <- effect(w$Y, idata, ~Time * Dose, ~Time + Dose)
w1 <- wide(d[d$Dose == "D1", ], "Time"); i1 <- w1$idata; i1[] <- lapply(i1, factor)
out[["One-way Time"]] <- effect(w1$Y, i1, ~Time, ~1)
w2 <- wide(d[d$Time == "T1", ], "Dose"); i2 <- w2$idata; i2[] <- lapply(i2, factor)
out[["One-way Dose"]] <- effect(w2$Y, i2, ~Dose, ~1)
fmt <- function(v) sprintf("%.17g", v)
items <- vapply(names(out), function(k) {
  e <- out[[k]]
  paste0('"', k, '": {', paste0('"', names(e), '": ', vapply(e, fmt, ""), collapse = ", "), "}")
}, "")
cat("{\n  ", paste(items, collapse = ",\n  "), "\n}\n", sep = "")
