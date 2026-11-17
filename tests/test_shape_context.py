"""Context actions change canonical drawings only, with atomic validation and real menu choices."""
from copy import deepcopy
import tkinter as tk
import unittest

from analisi.shape_context import edit_records, build_menu
from analisi.i18n import tr, set_language, active_language
from tests.test_shape_options import LINE, BOX


class ShapeContextRecordsTests(unittest.TestCase):
    def test_noop_and_invalid_action_do_not_mutate_input(self):
        records=[deepcopy(LINE)]
        got,selected=edit_records(records,LINE['id'],'width',LINE['width'])
        self.assertEqual(got,records);self.assertEqual(selected,LINE['id'])
        got,_=edit_records(records,LINE['id'],'arrow_heads','none');self.assertEqual(got,records)
        for action,value in [('width',0),('stroke','invalid color'),('hatch','cross'),('id','wrong')]:
            with self.subTest(action=action),self.assertRaises(ValueError):edit_records(records,LINE['id'],action,value)
        self.assertEqual(records,[LINE])

    def test_duplicate_remove_and_order_preserve_identity_and_appearance(self):
        records=[deepcopy(LINE),deepcopy(BOX)]
        duplicate,selected=edit_records(records,LINE['id'],'duplicate')
        self.assertNotEqual(selected,LINE['id']);self.assertEqual(len(duplicate),3)
        copied=duplicate[-1].copy();copied['id']=LINE['id'];self.assertEqual(copied,LINE)
        front,_=edit_records(records,LINE['id'],'front')
        self.assertEqual(front[-1],LINE)
        back,_=edit_records(records,BOX['id'],'back')
        self.assertEqual(back[0]['id'],BOX['id']);self.assertEqual(back[0]['layer'],'below')
        removed,selected=edit_records(records,LINE['id'],'remove')
        self.assertEqual(removed,[BOX]);self.assertIsNone(selected)
        self.assertEqual(records,[LINE,BOX])

    def test_supported_style_changes_keep_other_fields_and_legacy_defaults(self):
        for record,action,value in [(LINE,'stroke','#aa3355'),(LINE,'arrow_style','cap'),
                                    (LINE,'arrow_heads','both'),(LINE,'arrow_size',18.),
                                    (BOX,'hatch','cross'),(BOX,'fill',None)]:
            got,_=edit_records([record],record['id'],action,value)
            self.assertEqual(got[0],{**record,action:value})
        with self.assertRaises(ValueError):edit_records([LINE],BOX['id'],'remove')

    def test_duplicate_limit_is_checked_before_returning_a_candidate(self):
        import uuid
        records=[{**LINE,'id':str(uuid.uuid4())} for _ in range(100)]
        with self.assertRaises(ValueError):edit_records(records,records[0]['id'],'duplicate')
        self.assertEqual(len(records),100)


class ShapeContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:cls.root=tk.Tk()
        except tk.TclError as error:raise unittest.SkipTest(str(error))
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):cls.root.destroy()

    def test_integer_numeric_values_select_the_matching_float_preset_without_changing_records(self):
        record={**LINE,'width':2,'arrow_heads':'end','arrow_size':10}
        menu=build_menu(self.root,record,change=lambda *args:None,format_object=lambda:None,color=lambda key:None)
        try:
            for label,index in [('shape.context.width_line',4),('shape.arrow_size',1)]:
                item=next(i for i in range(menu.index('end')+1) if menu.type(i)=='cascade' and menu.entrycget(i,'label')==tr(label))
                child=menu.nametowidget(menu.entrycget(item,'menu'))
                self.assertEqual(child.getvar(child.entrycget(index,'variable')),child.entrycget(index,'value'))
            self.assertIs(type(record['width']),int);self.assertIs(type(record['arrow_size']),int)
        finally:menu.destroy()

    def test_real_translated_menu_invokes_canonical_choices(self):
        previous=active_language();self.addCleanup(set_language,previous)
        for language in ('en','it'):
            set_language(language);calls=[]
            menu=build_menu(self.root,{**LINE,'arrow_heads':'end'},
                            change=lambda key,value=None:calls.append((key,value)),
                            format_object=lambda:None,color=lambda key:None)
            try:
                labels=[menu.entrycget(i,'label') for i in range(menu.index('end')+1) if menu.type(i)!='separator']
                self.assertIn(tr('shape.context.format'),labels)
                index=next(i for i in range(menu.index('end')+1) if menu.type(i)=='cascade' and menu.entrycget(i,'label')==tr('shape.arrow_style'))
                submenu=menu.nametowidget(menu.entrycget(index,'menu'))
                submenu.invoke(2);self.assertEqual(calls[-1],('arrow_style','cap'))
            finally:menu.destroy()
