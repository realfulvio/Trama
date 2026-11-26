"""Persistent references to graphs owned by another project."""
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath


@dataclass(frozen=True)
class LayoutGraphLink:
    path: str
    title: str
    slot: int
    method: str
    label: str | None = None
    identity: str | None = None

    def __post_init__(self):
        def text(value, limit):
            return isinstance(value, str) and 0 < len(value) <= limit and "\0" not in value

        if (not text(self.path, 4096) or not any(kind(self.path).is_absolute()
                                                 for kind in (PureWindowsPath, PurePosixPath))
                or not text(self.title, 160) or not text(self.method, 160)
                or type(self.slot) is not int or not 0 <= self.slot < 65_536
                or (self.label is not None and not text(self.label, 320))
                or (self.identity is not None and not text(self.identity, 160))):
            raise ValueError("Invalid linked layout graph.")


def graph_links(value, count, panels, arrangement):
    """Canonical positions and references. Each link carries an offline drawing."""
    links = {}
    if not isinstance(value, (tuple, list)) or len(value) > count:
        raise ValueError("Invalid linked layout graph list.")
    for entry in value:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError("Invalid linked layout graph entry.")
        index, link = entry
        if (type(index) is not int or not 0 <= index < count or index in links
                or panels[index] is not None or arrangement.picture(index) is None):
            raise ValueError("A linked graph needs its own panel and saved drawing.")
        if isinstance(link, dict):
            try:
                link = LayoutGraphLink(**link)
            except TypeError as error:
                raise ValueError("Invalid linked layout graph.") from error
        if not isinstance(link, LayoutGraphLink):
            raise ValueError("Invalid linked layout graph.")
        links[index] = link
    return tuple(sorted(links.items()))
