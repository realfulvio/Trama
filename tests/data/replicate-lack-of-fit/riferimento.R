# Rscript riferimento.R [repliche.csv]
args <- commandArgs(trailingOnly = TRUE)
d <- read.csv(if (length(args) > 0) args[1] else "repliche.csv")
d <- d[complete.cases(d[c("X1", "X2", "Y")]), ]
d$condition <- interaction(d$X1, d$X2, drop = TRUE)
additive <- lm(Y ~ X1 + X2, data = d)
replicates <- lm(Y ~ condition, data = d)
print(anova(additive, replicates))
