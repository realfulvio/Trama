# Verifier correction during integration

`SHA256SUMS-package.txt` records the original work-package provenance; it is
not a current checksum manifest for the vendored directory. The integration
intentionally corrected only `verify.py`: the comparison accepts an array of
absolute tolerances directly instead of sending that array through NumPy's
scalar-only assertion-message formatter.

The comparison retains the original relative and elementwise absolute bounds.
No oracle values, expected JSON or CSV fixtures were regenerated or changed.
All 28 other vendored files listed in the original manifest still match it.
The package instruction/evidence files that were never vendored are not part
of this directory.

Original verifier SHA-256:
`d61f580240933e8e8da6a6397006b38f31d955d9579063e5e2b8f05a37d432d3`

Corrected verifier SHA-256:
`bec8cdc39c43a884e36ab3a5668fc2a49bd9fb41ed3b43db710540b03aac6b10`

Regression tests cover both accepting correctly bounded coefficients and
rejecting a tiny coefficient rounded incorrectly to zero.

