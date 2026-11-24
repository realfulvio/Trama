"""Shared page and panel coordinates for native layout previews and exports."""
from math import ceil

from matplotlib.colors import to_rgb
from matplotlib.figure import Figure

from .figure_export import MM

AUTO_PAPER = "Automatic"
WHITE = "#ffffff"
PANEL_SIZES = ("original", "width", "height", "both")
AXIS_ALIGNMENTS = ("none", "x", "y", "both")
PAPER_SIZES = {
    AUTO_PAPER: None,
    "A4 portrait": (210 / MM, 297 / MM),
    "A4 landscape": (297 / MM, 210 / MM),
    "Letter portrait": (8.5, 11),
    "Letter landscape": (11, 8.5),
}
PT = 72.0
CELL_W, CELL_H, TITLE_H = 4.2, 3.2, 0.4
PAD, LABEL_H = 0.08, 0.26
TITLE_SIZE, LABEL_SIZE = 14, 12
LABEL_PAD = .04


def page_size(columns, count, paper=AUTO_PAPER):
    """Physical size in inches for the chosen paper or the automatic grid."""
    return PAPER_SIZES[paper] or (CELL_W * columns, CELL_H * ceil(count / columns) + TITLE_H)


def panel_boxes(columns, sizes, paper=AUTO_PAPER, *, panel_size="original"):
    """Place each source figure in its cell as (left, top, scale) in page inches."""
    page_width, page_height = page_size(columns, len(sizes), paper)
    cell_width = page_width / columns
    cell_height = (page_height - TITLE_H) / ceil(len(sizes) / columns)
    width, height = cell_width - 2 * PAD, cell_height - LABEL_H - PAD
    if panel_size == "width":
        common_width = min(width, height / max(h / w for w, h in sizes))
        scales = [common_width / w for w, _ in sizes]
    elif panel_size == "height":
        common_height = min(height, width / max(w / h for w, h in sizes))
        scales = [common_height / h for _, h in sizes]
    else:
        scales = [min(width / w, height / h) for w, h in sizes]
    boxes = []
    for index, ((w, h), scale) in enumerate(zip(sizes, scales, strict=True)):
        row, column = divmod(index, columns)
        x = column * cell_width + PAD + (width - w * scale) / 2
        y = TITLE_H + row * cell_height + LABEL_H + (height - h * scale) / 2
        boxes.append((x, y, scale))
    return boxes


def page_ink(background):
    channels = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in to_rgb(background)]
    luminance = sum(weight * value for weight, value in zip((.2126, .7152, .0722), channels))
    return WHITE if luminance < .179 else "#000000"


def layout_frame(title, size, boxes, scale=1, *, background=WHITE, panel_letters=True):
    """A figure with the page background and title and optionally its panel letters."""
    width, height = size
    frame = Figure(figsize=size, facecolor=background)
    ink = page_ink(background)
    frame.suptitle(title, x=.5, y=1 - TITLE_H / 2 / height, ha="center", va="center",
                   fontsize=TITLE_SIZE * scale, fontweight="bold", parse_math=False, color=ink)
    if panel_letters:
        for index, (x, y, _) in enumerate(boxes):
            frame.text(x / width, 1 - (y - LABEL_PAD) / height, chr(ord("A") + index), ha="left", va="bottom",
                       fontsize=LABEL_SIZE * scale, fontweight="bold", parse_math=False, color=ink)
    return frame
