# Screenshot provenance — experiment families

Real screenshots of the application window and its dialogs, taken by `TRAMASTAT_SMOKE_ONLY=family-workflow` with `TRAMASTAT_SMOKE_SCREENSHOTS=1` (ImageMagick `import` on the X display) on Linux, Python 3.12, Tk 8.6, Xvfb 1600×1000, Standard theme, isolated preferences. Fixture data are synthetic (`analisi/family_workflow_smoke.py`). Images are copied without pixel edits.

The script drove the real Tk widgets. These images are not Windows evidence, not a manual mouse/keyboard acceptance and not a measurement of the system DPI.

- `preview-data-en.png`: Duplicate family… from a data table, English; SHA256 `c1011538110b9c957a959b35ac86eaa7ffa80dc09f9928fda0918c524600083b`.
- `name-taken-it.png`: a name already in use, Italian; the error stays under the field and the dialog stays open; SHA256 `344d72e2edbf237f524162cf1f7dc3f59852bf8ea114a9300ac79f6a414788ad`.
- `snapshot-en.png`: the only Info sheet is project-wide, so every copied table gets a local snapshot; SHA256 `ead6be54b9f8c7569bb957c1b532ae2dce9ef29558433d5e4c1aac18f266ab56`.
- `save-layouts-it.png`: Save family as…, Italian, with layouts included; SHA256 `7dfaf0eb8ebbc7e00deb1308689a4bf20567b4e27729d1a3fdca6885aa6d5517`.
