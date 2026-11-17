"""Weighted profile validation must not start any fit on the dialog thread."""
from unittest.mock import patch

from analisi.parameter_intervals import METHOD, PROFILE
from analisi.fit_weights import INVERSE_VARIANCE, OBSERVED_WEIGHTINGS, FITTED_WEIGHTINGS
from tests.test_graph_i18n import TkCase
from tests import test_parameter_intervals_dialog as parameter_dialog
from tests.test_parameter_weighting import FRAME


class WeightedProfileDialogTests(TkCase):
    drive = parameter_dialog.ParameterDialogTests.drive

    def test_all_weighted_profiles_are_deferred_to_the_worker(self):
        for weighting in (INVERSE_VARIANCE,*OBSERVED_WEIGHTINGS,*FITTED_WEIGHTINGS):
            with self.subTest(weighting=weighting):
                def action(d,seen):
                    d.controls[METHOD][1].set(PROFILE)
                    d.controls['Weighting'][1].set(weighting)
                    if weighting==INVERSE_VARIANCE:d.controls['SD column'][1].set('SD')
                    with patch('tramastat.analyse',side_effect=AssertionError('Must use worker')):
                        self.assertTrue(d.validate())
                    self.assertIsNone(d.processing_result)
                    self.assertEqual(d.result[1][METHOD],PROFILE)
                self.drive(action,frame=FRAME)

    def test_zero_observed_y_is_rejected_without_running_a_fit(self):
        def action(d,seen):
            d.controls[METHOD][1].set(PROFILE);d.controls['Weighting'][1].set('1/Y²')
            with (patch('tramastat.analyse',side_effect=AssertionError('No fitting')),
                  patch('tramastat.messagebox.showerror') as error):
                self.assertFalse(d.validate())
            self.assertEqual(d.focus_get(),d.field_rows['Weighting'][1])
            self.assertIn('zero',error.call_args.args[1])
        self.drive(action,frame=FRAME.assign(Y=[0.,*FRAME.Y.iloc[1:]]))

    def test_invalid_sd_is_rejected_on_sd_field_and_correctable_in_place(self):
        def action(d,seen):
            d.controls[METHOD][1].set(PROFILE);d.controls['Weighting'][1].set(INVERSE_VARIANCE)
            d.controls['SD column'][1].set('SD')
            d.data.loc[0,'SD']=0
            with (patch('tramastat.analyse',side_effect=AssertionError('No fitting')),
                  patch('tramastat.messagebox.showerror') as error):
                self.assertFalse(d.validate())
            self.assertTrue(error.called)
            self.assertEqual(d.focus_get(),d.field_rows['SD column'][1])
            d.data.loc[0,'SD']=.7
            self.assertTrue(d.validate())
        self.drive(action,frame=FRAME)

    def test_incomplete_observation_does_not_make_zero_y_invalid(self):
        def action(d,seen):
            d.controls[METHOD][1].set(PROFILE);d.controls['Weighting'][1].set('1/Y²')
            with patch('tramastat.analyse',side_effect=AssertionError('Must use worker')):
                self.assertTrue(d.validate())
        frame=FRAME.copy();frame.loc[0,'Y']=0;frame.loc[0,'X']=None
        self.drive(action,frame=frame)

    def test_weighted_runs_and_replicate_diagnostics_are_rejected_before_worker(self):
        for field in ('Runs test','Replicate lack of fit'):
            def action(d,seen):
                d.controls[METHOD][1].set(PROFILE)
                d.controls['Weighting'][1].set('1/Y²')
                d.controls[field][1].set(True)
                with (patch('tramastat.analyse',side_effect=AssertionError('No fitting')),
                      patch('tramastat.messagebox.showerror') as error):
                    self.assertFalse(d.validate())
                self.assertTrue(error.called)
                self.assertEqual(d.focus_get(),d.field_rows[field][1])
            self.drive(action,frame=FRAME)
