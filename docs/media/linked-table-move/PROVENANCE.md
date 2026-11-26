# Screenshot provenance — interactive linked table movement

Real screenshots of Trama on Classica Qt (`PySide6 6.12.0`, base `v0.113.0` + branch `agy/sposta-tabelle-collegate`), captured via `python -m trama_qt.linked_table_move_smoke` on synthetic project `tests/data/qt_linked_table_move/tabelle-in-figura.alab`.

Environment (`santabianca-hcok`, `Windows-10-10.0.19045-SP0`, `QPA=windows`, console session 1 on `ZOWIE XL LCD` 1920×1080):
- 100% screenshots (`win-100-*`): native Windows 96 DPI (`devicePixelRatio = 1.0`, system scale).
- 150% screenshots (`win-150-*`): real Windows desktop (`QPA=windows`) with `QT_SCALE_FACTOR=1.5` (`devicePixelRatio = 1.5`, logical desktop 1280×693; Windows registry display scale left untouched at 96 DPI).

Images are unmodified captures of the running window/dialog:

- `win-100-en-light-graph-selected.png` SHA256 `cb1971af067a5e08b6e2a4fccc078a8b3f524e14de1f825eb4b7a9e7a96d9013`
- `win-100-it-dark-dragging-guides.png` SHA256 `d3b1f3c231c2d9f6746619ee03878a34ce2182e05356335f3224accdb3182616`
- `win-100-it-dark-dialog.png` SHA256 `ada29c8aadab47f4c77d0d307692426311acfb2a093fc76169fece5540a4af24`
- `win-150-it-light-dragging-guides.png` SHA256 `20f26a11e9dcb6b3c673719e8163176bb295c1c52f07a40ebd50a49835258be5`
- `win-150-en-dark-layout-moved.png` SHA256 `e66d8e7687b00b7f8b17848efc86ee82201a1ba0f4cf9cad50052b06b1909b4a`
