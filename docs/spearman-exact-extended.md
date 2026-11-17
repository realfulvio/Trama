# Exact Spearman: extended budget

Detailed **Correlation** and **Correlate against control** support exact labelled
permutation p values for up to 17 complete pairs, including ties. Choose
**Spearman exact budget → Extended (17 pairs)**. New dialogs start with this
budget. Existing recipes without the new field retain **Standard (9 pairs)**;
opening and confirming an old recipe does not silently raise its budget.
The correlation-matrix analysis keeps its existing independent policy.

The three tails use inclusive integer products of normalized average ranks.
Two-sided means at least as far from the permutation mean in either direction;
it is not twice the smaller one-sided tail for an asymmetric tied distribution.
Confidence intervals retain the existing separate Bonett–Wright rule (n ≥ 11).

## Resources, cancellation, and reporting

The extended calculation plans storage before allocating dense arrays. It
allows at most 4,000,000 transitions across distinct rank-multiset distributions
and 384 MiB of planned live dense storage plus state/cache allowances. Identical
null distributions are counted once within one control family. No extended
result cache survives the analysis. These are algorithmic limits, not a bound
on the entire application's resident memory or Python's allocator retention.

**Automatic** uses the t approximation when n or a resource limit is exceeded;
the result identifies the method and reason for each response. **Exact** raises
an error rather than substituting an approximation. Resource errors detected by
the worker reopen the candidate dialog with its settings and the responsible
field. A constant response is unavailable rather than a resource fallback.

Counting runs on the analysis worker. **Cancel calculation** stops between
bounded batches of states. A cancelled new analysis adds no recipe; cancelling
an edited analysis preserves the last confirmed recipe and result. After a data
edit, invalidated results remain invalidated until a new calculation succeeds.
The approximation option ignores the inactive exact-budget field.

Labels and errors are available in English and Italian; recipes store canonical
values. Numerical result sheets follow the existing English worksheet convention.

