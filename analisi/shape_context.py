"""Validated drawing-only context operations and canonical EN/IT menu choices.

``edit_records`` and the choice tables are toolkit-free (the Qt window builds its own menu from them);
only ``build_menu`` creates Tk controls.
"""
from .graph_shapes import (ARROW_HEADS, ARROW_SIZE, ARROW_STYLES, HATCHES, LINE_STYLES,
                           validate_shapes)
from .i18n import tr
from .shape_objects import duplicate_object, edit_objects, is_locked, selected_objects

WIDTHS = (.25, .5, 1., 1.5, 2., 3., 4., 6., 8., 12.)
ENDING_SIZES = (6., 10., 14., 18., 24., 32., 40.)
DEFAULTS = {'arrow_heads':'none', 'arrow_style':'open', 'arrow_size':ARROW_SIZE, 'hatch':'none'}
FIELDS = {'stroke', 'width', 'line_style', 'fill', 'hatch', 'hatch_color', 'arrow_heads', 'arrow_style', 'arrow_size'}


def edit_records(records, shape_id, action, value=None):
    """Return a complete canonical candidate and selected ID; the input is never modified."""
    candidate = validate_shapes(records)
    objects = selected_objects(candidate, [shape_id])
    if not objects:
        raise ValueError(tr("shape.context.missing"))
    members = objects[0]
    if action in ("ungroup", "lock", "unlock"):
        return edit_objects(candidate, [shape_id], action), shape_id
    if is_locked(members):
        raise ValueError(tr("shape.objects.locked"))
    record = next(record for record in members if record["id"] == shape_id)
    selected = shape_id
    if action in FIELDS:
        if len(members) > 1:
            raise ValueError(tr("shape.objects.ungroup_first"))
        if action == "hatch_color" and value is None:
            record.pop(action, None)
        elif record.get(action, DEFAULTS.get(action)) != value:
            record[action] = value
    elif action == "duplicate":
        copies = duplicate_object(members)
        selected = copies[members.index(record)]["id"]
        candidate.extend(copies)
    elif action in ("remove", "front", "back"):
        ids = {member["id"] for member in members}
        candidate = [item for item in candidate if item["id"] not in ids]
        if action == "remove":
            selected = None
        else:
            for member in members:
                member["layer"] = "above" if action == "front" else "below"
            if action == "front":
                candidate.extend(members)
            else:
                candidate[:0] = members
    else:
        raise ValueError(tr("shape.context.invalid"))
    return validate_shapes(candidate), selected


def build_menu(master, record, *, change, format_object, color, clipboard=None):
    """Create actual Tk controls. Callbacks receive canonical values, never translated labels."""
    import tkinter as tk

    menu = tk.Menu(master,tearoff=False)
    menu._shape_variables=[]
    menu.add_command(label=tr('shape.context.format'),command=format_object)
    menu.add_separator()
    if clipboard is not None:
        for action, shortcut in (('cut','Ctrl+X'),('copy','Ctrl+C'),('paste','Ctrl+V')):
            menu.add_command(label=tr('shape.clipboard.'+action),accelerator=shortcut,
                             command=lambda action=action:clipboard(action))
        menu.add_separator()
    suffix='line' if record['kind']=='line' else 'area'
    menu.add_command(label=tr('shape.context.color_'+suffix),command=lambda:color('stroke'))

    def choices(label,key,values,*,translated=True,enabled=True,units=False):
        child=tk.Menu(menu,tearoff=False)
        current=record.get(key,DEFAULTS.get(key))
        # Display numeric equality consistently without normalizing or rewriting a saved record.
        variable=tk.StringVar(menu,value=str(float(current)) if not translated else str(current))
        menu._shape_variables.append(variable)
        for value in values:
            caption=tr('shape.option.'+value) if translated else f'{value:g}' + (' pt' if units else '')
            child.add_radiobutton(label=caption,variable=variable,value=str(value),
                                  command=lambda value=value:change(key,value))
        menu.add_cascade(label=tr(label),menu=child,state='normal' if enabled else 'disabled')

    choices('shape.context.width_'+suffix,'width',WIDTHS,translated=False,units=True)
    choices('shape.context.style_'+suffix,'line_style',LINE_STYLES)
    if record['kind']=='line':
        choices('shape.arrow_heads','arrow_heads',ARROW_HEADS)
        active=record.get('arrow_heads','none')!='none'
        choices('shape.arrow_style','arrow_style',ARROW_STYLES,enabled=active)
        choices('shape.arrow_size','arrow_size',ENDING_SIZES,translated=False,units=True,enabled=active)
    else:
        menu.add_command(label=tr('shape.context.fill_color'),command=lambda:color('fill'))
        menu.add_command(label=tr('shape.context.no_fill'),command=lambda:change('fill',None))
        choices('shape.hatch','hatch',HATCHES)
        state='normal' if record.get('hatch','none')!='none' else 'disabled'
        menu.add_command(label=tr('shape.context.pattern_color'),command=lambda:color('hatch_color'),state=state)
        menu.add_command(label=tr('shape.context.pattern_follow'),command=lambda:change('hatch_color',None),state=state)
    menu.add_separator()
    menu.add_command(label=tr('shape.context.duplicate'),command=lambda:change('duplicate'))
    menu.add_command(label=tr('shape.context.remove'),command=lambda:change('remove'))
    menu.add_separator()
    menu.add_command(label=tr('shape.context.front'),command=lambda:change('front'))
    menu.add_command(label=tr('shape.context.back'),command=lambda:change('back'))
    return menu
