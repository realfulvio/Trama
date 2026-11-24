"""Atomic drawing arrangement in primary-axis display coordinates, with no model mutation."""
import numpy as np
from .graph_shapes import on_axis_domain, validate_shapes
from .shape_objects import is_locked, selected_objects, shape_transform, translated_shape

HORIZONTAL=('none','left','center','right','distribute')
VERTICAL=('none','top','middle','bottom','distribute')
PIXEL_TOLERANCE=1e-7


class ArrangementError(ValueError):
    def __init__(self,field,key):
        self.field,self.key=field,key
        super().__init__(key)


def _offsets(bounds,axis,mode):
    low=bounds[:,0,axis];high=bounds[:,1,axis]
    if mode=='none':return np.zeros(len(low))
    if mode in ('left','bottom'):return low.min()-low
    if mode in ('right','top'):return high.max()-high
    if mode in ('center','middle'):return (low.min()+high.max()-low-high)/2
    lengths=high-low;span=high.max()-low.min()
    available=span-float(lengths.sum())
    if available < -PIXEL_TOLERANCE:
        raise ArrangementError('horizontal' if axis==0 else 'vertical','space')
    gap=max(0.,available)/(len(low)-1)
    offsets=np.zeros(len(low));cursor=float(low.min())
    for index in np.argsort(low,kind='stable'):
        offsets[index]=cursor-low[index]
        cursor+=lengths[index]+gap
    return offsets


def arrange_shapes(axes,records,selected_ids,*,horizontal='none',vertical='none'):
    """Return one validated complete candidate; bounds exclude pen width and arrow decorations.

    Alignment uses the enclosing selected endpoint rectangle. Distribution preserves its outer
    bounds and equalizes nonnegative edge gaps. Original coordinate units and style keys remain.
    """
    candidate=validate_shapes(records)
    if horizontal not in HORIZONTAL:raise ArrangementError('horizontal','mode')
    if vertical not in VERTICAL:raise ArrangementError('vertical','mode')
    if (not isinstance(selected_ids,(list,tuple)) or not all(isinstance(i,str) for i in selected_ids)
            or len(selected_ids)<2 or len(set(selected_ids))!=len(selected_ids)):
        raise ArrangementError('selection','selection')
    known={r['id']:i for i,r in enumerate(candidate)}
    if any(i not in known for i in selected_ids):raise ArrangementError('selection','selection')
    objects = selected_objects(candidate, selected_ids)
    if len(objects) < 2:
        raise ArrangementError("selection", "selection")
    if "distribute" in (horizontal, vertical) and len(objects) < 3:
        raise ArrangementError("selection", "three")
    if axes.name != "rectilinear":
        raise ArrangementError("selection", "domain")
    bounds = []
    for members in objects:
        if is_locked(members):
            raise ArrangementError("selection", "locked")
        if not all(on_axis_domain(axes, record) for record in members):
            raise ArrangementError("selection", "domain")
        pixels = np.concatenate([shape_transform(axes, record).transform(record["points"]) for record in members])
        if not np.all(np.isfinite(pixels)):
            raise ArrangementError("selection", "domain")
        bounds.append((pixels.min(axis=0), pixels.max(axis=0)))
    bounds = np.asarray(bounds)
    offsets = np.column_stack((_offsets(bounds, 0, horizontal), _offsets(bounds, 1, vertical)))
    offsets[np.abs(offsets) <= PIXEL_TOLERANCE] = 0
    try:
        for members, offset in zip(objects, offsets, strict=True):
            for record in members:
                candidate[known[record["id"]]] = translated_shape(axes, record, offset)
        return validate_shapes(candidate)
    except (ValueError, TypeError, OverflowError):
        raise ArrangementError("selection", "domain") from None
