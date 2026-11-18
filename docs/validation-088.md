# Trama 0.88.0 beta verification

Application source `24d20bc9b17e16ddd58fb3c9e63180591be53944`.

| Check | Result |
| --- | --- |
| Linux/Tk 8.6 unit suite | 2,668 passed |
| Native Windows unit suite | 2,667 passed, 1 skipped |
| Categorical scatter contract | 10/10 passed |
| Linux GUI | Complete regression at 1920×1080 passed |
| Windows portable | Six checks passed covering both themes and sizes, complete regression and animated startup |
| Frozen application | 274 modules and entry point verified against source |
| Original desktop resolution | Restored |

The Windows account lacked permission to create a symbolic link, so one check was skipped.

Windows desktop checks drove actual application controls programmatically at 96 DPI. The capture and export use synthetic worksheets. The tested ZIP SHA256 is `79bb1d3fbfe26cb4b764839e72e49722ed0e879e4aa301a2c94f12b26a7a1e6d`. The published manifest records the final digest and the number of unchanged non-document files.
