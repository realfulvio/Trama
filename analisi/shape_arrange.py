"""Atomic drawing arrangement in primary-axis display coordinates, with no model mutation."""
import numpy as np
from .graph_shapes import on_axis_domain, validate_shapes

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
    if 'distribute' in (horizontal,vertical) and len(selected_ids)<3:
        raise ArrangementError('selection','three')
    if axes.name!='rectilinear':raise ArrangementError('selection','domain')
    indices=[known[i] for i in selected_ids]
    transforms=[];pixels=[]
    for index in indices:
        record=candidate[index]
        if not on_axis_domain(axes,record):raise ArrangementError('selection','domain')
        transform=axes.transAxes if record['units']=='axes' else axes.transData
        points=np.asarray(transform.transform(record['points']),dtype=float)
        if not np.all(np.isfinite(points)):raise ArrangementError('selection','domain')
        transforms.append(transform);pixels.append(points)
    pixels=np.asarray(pixels)
    bounds=np.stack((pixels.min(axis=1),pixels.max(axis=1)),axis=1)
    offsets=np.column_stack((_offsets(bounds,0,horizontal),_offsets(bounds,1,vertical)))
    offsets[np.abs(offsets)<=PIXEL_TOLERANCE]=0
    for index,transform,points,offset in zip(indices,transforms,pixels,offsets):
        if not np.any(offset):continue
        record=candidate[index]
        with np.errstate(over='ignore',invalid='ignore'):
            moved=np.asarray(transform.inverted().transform(points+offset),dtype=float)
        if not np.all(np.isfinite(moved)):raise ArrangementError('selection','domain')
        # Inverting a transform must not rewrite a coordinate dimension the user left untouched.
        for axis in range(2):
            if offset[axis]==0:moved[:,axis]=np.asarray(record['points'])[:,axis]
        if record['units']=='axes':
            near=(moved>=-1e-12)&(moved<=1+1e-12)
            moved=np.where(near,np.clip(moved,0,1),moved)
        record['points']=moved.tolist()
        if not on_axis_domain(axes,record):raise ArrangementError('selection','domain')
    try:return validate_shapes(candidate)
    except ValueError:raise ArrangementError('selection','domain') from None
