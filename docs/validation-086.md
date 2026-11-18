# Trama 0.86.0 beta verification

Application source `34cc7d65707a9892b06131bff7b1829be9f032b5`.

| Check | Result |
| --- | --- |
| Linux/Tk 8.6 unit suite | 2,661 passed |
| Native Windows unit suite | 2,660 passed, 1 skipped |
| Worksheet formulas and cluster consensus contract | 88/88 passed |
| Linux GUI | Complete regression at 1920×1080 passed |
| Windows portable | Seven checks passed across the two screen sizes and themes, including worksheet statistics, K-means consensus, full regression and animated startup |
| Frozen application | 271 modules and entry point verified against source |
| Original desktop resolution | Restored |

The Windows account lacked permission to create a symbolic link, so one check was skipped.

Desktop checks drove actual Windows application controls programmatically at 1024×768 and 1920×1080 and 96 native DPI. The release captures use synthetic data.

The tested ZIP SHA256 is `fb80bf084844d7667aa370c812518304ad5bb2235db3e4f86281ab1968d4e045`. The release manifest records the distributed archive checksum and the count of unchanged non-document files.
