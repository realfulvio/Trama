# Trama 0.89.0 beta verification

Application source `172adc5ac13c4922f7c8cf62cd193f9279d863c2`.

| Check | Result |
| --- | --- |
| Linux unit suite | 2,673 passed |
| Native Windows unit suite | 2,672 passed, 1 skipped |
| PCA overlay numerical and integration contract | 4/4 passed |
| Linux GUI | Complete regression at 1920×1080 passed |
| Windows portable | Six checks passed across both themes and resolutions, complete regression, and animated startup |
| Frozen application | 275 modules and entry point verified against source |
| Original desktop resolution | Restored |

The test account lacked permission to create symbolic links, so one check was skipped.

Native Windows checks drove application controls programmatically at 96 DPI. The capture and export use a synthetic worksheet. The tested ZIP SHA256 is `fa60c8dc48b464c8f0a784bce61f98d7a7813a43a115cac7735c2fb8a42a6e12`. The published manifest records the final archive digest and the comparison of non-document members.
