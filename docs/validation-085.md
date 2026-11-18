# Trama 0.85.0 beta verification

Application source `5463c35d0b690650d3192e6473a9172c5182c241`.

| Check | Result |
| --- | --- |
| Linux/Tk 8.6 unit suite | 2,650 passed |
| Native Windows unit suite | 2,649 passed, 1 skipped |
| Selected ANOVA terms contract | 11/11 passed |
| Linux GUI | Complete regression at 1920×1080 passed |
| Windows portable | Ten checks passed, including both themes and both screen sizes, the complete regression and animated startup |
| Frozen application | 270 modules and entry point verified against source |
| Original desktop resolution | Restored |

The Windows account lacked permission to create a symbolic link, so one check was skipped.

The Windows desktop checks used 1024×768 and 1920×1080 at native 96 DPI. The checks drove the real application controls programmatically. Published captures use synthetic data.

The tested ZIP SHA256 is `eaba58d92f43a962d1ce95ca754a7ad925ed7c0bfcf522eac0ba9d1cf9892a1b`. The published manifest records the release archive SHA256 and the count of unchanged non-document files.
