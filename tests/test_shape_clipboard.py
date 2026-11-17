"""Independent clipboard protocol: identities, formatting and bounded untrusted text."""
from copy import deepcopy
import importlib.util
import json
import unittest
import uuid

from tests.test_shape_options import LINE, BOX


class DrawingClipboardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('analisi.shape_clipboard'),
                             'Native drawing clipboard protocol is missing')
        from analisi import shape_clipboard
        self.clip = shape_clipboard

    def test_all_native_appearances_round_trip_without_inserting_defaults(self):
        for shape in (LINE, BOX, {**LINE, 'arrow_heads':'both', 'arrow_style':'cap', 'arrow_size':18},
                      {**BOX, 'hatch':'cross', 'fill':None, 'units':'data', 'points':[[-2.,1.],[3.,8.]]}):
            with self.subTest(shape=shape):
                before=deepcopy(shape)
                text=self.clip.dump_shape(shape)
                self.assertEqual(self.clip.load_shape(text), before)
                self.assertEqual(shape, before)
                json.loads(text)

    def test_paste_always_uses_fresh_identity_and_does_not_alias(self):
        original=[deepcopy(LINE)]
        text=self.clip.dump_shape(BOX)
        first,selected=self.clip.paste_shape(original,text)
        second,other=self.clip.paste_shape(first,text)
        self.assertNotIn(selected,(LINE['id'],BOX['id']))
        self.assertNotIn(other,(selected,LINE['id'],BOX['id']))
        self.assertEqual(str(uuid.UUID(selected)),selected)
        expected=deepcopy(BOX);expected['id']=selected
        self.assertEqual(first,[LINE,expected])
        self.assertEqual(len(second),3)
        first[0]['points'][0][0]=.99
        self.assertEqual(original,[LINE])
        self.assertEqual(second[0],LINE)

    def test_foreign_clipboard_and_unknown_envelopes_are_rejected(self):
        valid=json.loads(self.clip.dump_shape(LINE))
        for bad in ('', '1\t2\n3\t4', 'null', '[]', '{}', json.dumps(LINE),
                    json.dumps({**valid,'format':'other'}), json.dumps({**valid,'version':2}),
                    json.dumps({**valid,'version':True}), json.dumps({**valid,'extra':1})):
            with self.subTest(bad=bad[:80]):
                with self.assertRaises(ValueError): self.clip.load_shape(bad)

    def test_duplicate_keys_nonfinite_values_and_invalid_shape_fail(self):
        text=self.clip.dump_shape(LINE)
        for bad in (text.replace('"version":1','"version":1,"version":1'),
                    text.replace('"width":1.5','"width":NaN'),
                    text.replace('"width":1.5','"width":Infinity'),
                    text.replace('"width":1.5','"width":1e999'),
                    text.replace('"width":1.5','"width":0'),
                    text.replace('"kind":"line"','"kind":"__import__"')):
            self.assertNotEqual(text,bad)
            with self.subTest(bad=bad[:90]):
                with self.assertRaises(ValueError): self.clip.load_shape(bad)

    def test_size_depth_and_nontext_inputs_fail_with_value_error(self):
        for bad in (None, b'not text', 3, 'x'*(self.clip.MAX_TEXT+1), '['*2000+']'*2000):
            with self.subTest(kind=type(bad)):
                with self.assertRaises(ValueError): self.clip.load_shape(bad)

    def test_limit_and_invalid_existing_records_do_not_mutate_input(self):
        records=[{**deepcopy(LINE),'id':str(uuid.uuid4())} for _ in range(100)]
        before=deepcopy(records)
        with self.assertRaises(ValueError):self.clip.paste_shape(records,self.clip.dump_shape(BOX))
        self.assertEqual(records,before)
        with self.assertRaises(ValueError):self.clip.paste_shape([LINE,LINE],self.clip.dump_shape(BOX))

    def test_copy_rejects_noncanonical_source(self):
        for source in ({**LINE,'id':'bad'},{**LINE,'width':0},{**LINE,'filename':'unexpected'}):
            with self.assertRaises(ValueError):self.clip.dump_shape(source)

    def test_integer_properties_remain_integers(self):
        record={**LINE,'width':2,'arrow_size':10,'arrow_heads':'end'}
        restored=self.clip.load_shape(self.clip.dump_shape(record))
        self.assertIs(type(restored['width']),int)
        self.assertIs(type(restored['arrow_size']),int)
