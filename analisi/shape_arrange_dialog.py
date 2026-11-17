"""A compact transactional arrangement dialog for a graph's native drawing records."""
from copy import deepcopy
import tkinter as tk
from tkinter import simpledialog,ttk
from .graph_dialog import ChoiceBinding
from .graph_shape_dialog import describe_shape
from .graph_shapes import validate_shapes
from .shape_arrange import ArrangementError,HORIZONTAL,VERTICAL,arrange_shapes
from .i18n import tr


class ArrangeShapesDialog(simpledialog.Dialog):
    def __init__(self,parent,axes,records,*,preview=None):
        self.axes=axes;self.confirmed=validate_shapes(records)
        self.preview_callback=preview;self.shown=None;self.result=None;self.accepted=False
        super().__init__(parent,tr('arrange.title'))

    def body(self,master):
        self.body_frame=master;master.pack_configure(fill='both',expand=True)
        frame=ttk.Frame(master,padding=8);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=tr('arrange.hint'),wraplength=580,justify='left').pack(anchor='w',pady=(0,8))
        table=ttk.Frame(frame);table.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(table,columns=('number','kind','units'),show='headings',height=7,selectmode='extended')
        for key,label,width in (('number','#',45),('kind',tr('shape.kind'),180),('units',tr('shape.units'),310)):
            self.tree.heading(key,text=label);self.tree.column(key,width=width,anchor='w')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
        for number,record in enumerate(self.confirmed,1):
            kind,units,_,_=describe_shape(record)
            self.tree.insert('','end',iid=record['id'],values=(number,kind,units))
        self.tree.selection_set(self.tree.get_children())
        self.tree.bind('<Control-a>',self.select_all)
        form=ttk.Frame(frame);form.pack(fill='x',pady=(10,4))
        self.fields={};self.widgets={};self.bindings={}
        for row,(key,values) in enumerate((('horizontal',HORIZONTAL),('vertical',VERTICAL))):
            ttk.Label(form,text=tr('arrange.'+key)).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
            variable=self.fields[key]=tk.StringVar(self,value='none')
            widget=self.widgets[key]=ttk.Combobox(form,state='readonly',width=36)
            widget.grid(row=row,column=1,sticky='ew',pady=4)
            self.bindings[key]=ChoiceBinding(widget,variable,values,{v:tr('arrange.option.'+v) for v in values})
        form.columnconfigure(1,weight=1)
        self.message=ttk.Label(frame,foreground='#b00020',wraplength=580,justify='left')
        self.message.pack(fill='x',pady=(4,0))
        return self.tree

    def buttonbox(self):
        row=ttk.Frame(self,padding=8);row.pack(side='bottom',fill='x',before=self.body_frame)
        self.cancel_button=ttk.Button(row,text=tr('setup.cancel'),command=self.cancel);self.cancel_button.pack(side='right')
        self.apply_button=ttk.Button(row,text=tr('graph.format.apply'),style='Action.TButton',command=self.ok)
        self.apply_button.pack(side='right',padx=6)
        self.preview_button=ttk.Button(row,text=tr('shape.preview'),command=self.preview);self.preview_button.pack(side='right')
        for button in (self.cancel_button,self.apply_button,self.preview_button):
            button.bind('<Return>',lambda event:event.widget.invoke() or 'break')
        self.bind('<Escape>',self.cancel)

    def select_all(self,event=None):
        self.tree.selection_set(self.tree.get_children());return 'break'

    def read_candidate(self):
        options={}
        for key,binding in self.bindings.items():
            value=self.fields[key].get()
            if value in binding.labels:value=binding.values[binding.labels.index(value)]
            if value not in binding.values:raise ArrangementError(key,'mode')
            options[key]=value
        return arrange_shapes(self.axes,self.confirmed,list(self.tree.selection()),**options)

    def report(self,error):
        self.message.configure(text=tr('arrange.error.'+getattr(error,'key','domain')))
        widget=self.tree if getattr(error,'field','selection')=='selection' else self.widgets[error.field]
        widget.focus_set()

    def preview(self):
        try:
            candidate=self.read_candidate()
            warning=self.preview_callback(deepcopy(candidate)) if self.preview_callback else None
        except ValueError as error:
            self.report(error);return False
        self.shown=deepcopy(candidate);self.message.configure(text=warning or '')
        return True

    def validate(self):
        try:self.result=self.read_candidate()
        except ValueError as error:
            self.result=None;self.report(error);return False
        return True

    def ok(self,event=None):
        if not self.winfo_exists():return None
        # Dialog.ok would refocus initial_focus after validate(), hiding the actual field error.
        if not self.validate():return 'break'
        self.withdraw();self.update_idletasks()
        try:self.apply()
        finally:self.cancel()

    def apply(self):
        self.accepted=True  # The caller commits only this confirmed candidate after the modal closes.

    def cancel(self,event=None):
        if not self.accepted:
            if self.winfo_exists() and self.shown is not None and self.preview_callback:self.preview_callback(None)
            self.result=None
        super().cancel(event)
