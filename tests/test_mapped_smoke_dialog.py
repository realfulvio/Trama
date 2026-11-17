"""A smoke callback must not touch a constructed but still unmapped modal window."""
import tkinter as tk
from tkinter import simpledialog
import unittest
from analisi import graph_language_smoke as driver

class MappedSmokeDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:cls.root=tk.Tk()
        except tk.TclError as error:raise unittest.SkipTest(str(error))
        cls.root.withdraw()
    @classmethod
    def tearDownClass(cls):cls.root.destroy()
    def setUp(self):
        self.assertTrue(hasattr(driver,'drive_mapped_dialog'),'The graph-language driver does not wait for mapping')
    def test_constructed_hidden_dialog_is_not_operated_until_it_maps(self):
        class Dialog(tk.Toplevel):
            def cancel(self):self.destroy()
        window=Dialog(self.root);window.withdraw();seen=[];errors=[]
        driver.drive_mapped_dialog(self.root,Dialog,lambda w:seen.append(w.winfo_viewable()),errors,timeout=.5)
        show=self.root.after(120,window.deiconify);stop=self.root.after(250,self.root.quit)
        self.root.mainloop();self.assertEqual(seen,[1]);self.assertFalse(errors);window.destroy()
    def test_missing_dialog_produces_a_bounded_failure(self):
        errors=[];seen=[]
        driver.drive_mapped_dialog(self.root,tk.Toplevel,seen.append,errors,timeout=.05)
        self.root.after(140,self.root.quit);self.root.mainloop()
        self.assertFalse(seen);self.assertEqual(len(errors),1)
    def test_never_mapped_dialog_is_cancelled_on_timeout(self):
        class Dialog(tk.Toplevel):
            def cancel(self):self.destroy()
        window=Dialog(self.root);window.withdraw();errors=[];seen=[]
        driver.drive_mapped_dialog(self.root,Dialog,seen.append,errors,timeout=.05)
        self.root.after(140,self.root.quit);self.root.mainloop()
        self.assertFalse(seen);self.assertEqual(len(errors),1);self.assertFalse(window.winfo_exists())

    def test_visible_modal_waits_for_its_constructor_to_acquire_the_grab(self):
        seen, errors = [], []
        class Dialog(simpledialog.Dialog):
            def body(dialog, master):
                return tk.Entry(master)
            def grab_set(dialog):
                # A visible modal is still being initialized while its constructor waits here.
                self.root.after(100, lambda: super(Dialog, dialog).grab_set())
        def ready(dialog):
            seen.append(dialog.grab_current() is dialog)
            dialog.cancel()
        driver.drive_mapped_dialog(self.root, Dialog, ready, errors, timeout=.8)
        Dialog(self.root)
        self.assertEqual(seen, [True])
        self.assertFalse(errors)
