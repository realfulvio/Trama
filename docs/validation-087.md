# Trama 0.87.0 beta verification

Application source `7af47a50afcf7740aee09a6c8178ff0a298fceb2`.

| Check | Result |
| --- | --- |
| Linux/Tk 8.6 unit suite | 2,666 passed |
| Native Windows unit suite | 2,665 passed, 1 skipped |
| PCA plots and reports contract | 24/24 passed |
| Linux GUI | Complete regression at 1920×1080 passed |
| Windows portable | Six checks passed covering both themes and sizes, the complete regression and animated startup |
| Frozen application | 272 modules and entry point verified against source |
| Original desktop resolution | Restored |

The Windows account lacked permission to create a symbolic link, so one check was skipped.

The real Windows application controls were driven programmatically at native 96 DPI. Release captures use synthetic data. The tested ZIP SHA256 is `279fca211b5c787ab1ccf0a14d676e61ef34411e3e0b3cb345dc53ab72a16d42`. The release manifest lists the distributed checksum and the number of unchanged non-document files.
