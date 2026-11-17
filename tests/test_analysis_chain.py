"""Independent contracts for persistent, branching result-input graphs."""
from types import SimpleNamespace
from unittest import TestCase
from uuid import UUID

import numpy as np
import pandas as pd

from analisi.analysis_chain import (
    AnalysisGraph, ChainCancelled, ResultSource, evaluate_graph, result_frame,
)


def uid(number):
    return str(UUID(int=number))


class AnalysisGraphTests(TestCase):
    def graph(self):
        return AnalysisGraph([(uid(1), None), (uid(2), ResultSource(uid(1), 'Data')),
                              (uid(3), ResultSource(uid(2), 'Data')),
                              (uid(4), ResultSource(uid(1), 'Data')), (uid(5), None)])

    def test_branching_order_is_topological_even_when_storage_is_reversed(self):
        graph = AnalysisGraph(list(reversed(list(self.graph().sources.items()))))
        order = graph.order
        self.assertLess(order.index(uid(1)), order.index(uid(2)))
        self.assertLess(order.index(uid(2)), order.index(uid(3)))
        self.assertLess(order.index(uid(1)), order.index(uid(4)))
        self.assertEqual(set(graph.affected([uid(2)])), {uid(2), uid(3)})

    def test_missing_ancestor_refresh_includes_its_other_descendants(self):
        graph = self.graph()
        self.assertEqual(set(graph.affected([uid(3)], unavailable={uid(1), uid(2)})),
                         {uid(1), uid(2), uid(3), uid(4)})
        self.assertEqual(graph.affected([uid(3)]), [uid(3)])

    def test_invalid_identifiers_duplicate_nodes_orphans_and_cycles_are_rejected(self):
        cases = [[(uid(1), None), (uid(1), None)],
                 [(uid(1), ResultSource(uid(9), 'Data'))],
                 [(uid(1), ResultSource(uid(1), 'Data'))],
                 [(uid(1), ResultSource(uid(2), 'Data')),
                  (uid(2), ResultSource(uid(1), 'Data'))]]
        for nodes in cases:
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                AnalysisGraph(nodes)
        with self.assertRaises(ValueError):
            ResultSource('not an identity', 'Data')

    def test_long_chains_use_no_recursive_traversal(self):
        nodes = [(uid(1), None)] + [(uid(i), ResultSource(uid(i-1), 'Data')) for i in range(2, 1501)]
        graph = AnalysisGraph(nodes)
        self.assertEqual(len(graph.affected([uid(1500)], unavailable=set(graph.sources))), 1500)

    def test_result_input_preserves_labels_and_replicate_roles_without_mutating_output(self):
        frame = pd.DataFrame({'X': [1., 2.], 'Y [1]': [3., 4.], 'Y [2]': [5., 6.]},
                             index=pd.Index(['a', 'b'], name='Subject'))
        frame.attrs['worksheet_roles'] = {'x': ['X'], 'y': [['Y [1]', 'Y [2]']]}
        result = SimpleNamespace(tables={'Transformed': frame})
        converted = result_frame(result, 'Transformed')
        self.assertEqual(converted.columns.tolist(), ['Subject', 'X', 'Y [1]', 'Y [2]'])
        self.assertEqual(converted.Subject.tolist(), ['a', 'b'])
        self.assertEqual(converted.attrs['worksheet_roles'], frame.attrs['worksheet_roles'])
        converted.iloc[0, 1] = 999
        self.assertEqual(frame.iloc[0, 0], 1.)
        with self.assertRaisesRegex(ValueError, 'Missing'):
            result_frame(result, 'Missing')

    def test_edit_propagates_once_per_node_and_matches_an_independent_linear_fit(self):
        graph = self.graph()
        raw = pd.DataFrame({'X': [0., 1., 2., 3.], 'Y': [1., 3., 5., 7.]})
        calls = []

        def compute(node, frame):
            calls.append(node)
            if node == uid(1):
                return SimpleNamespace(tables={'Data': frame.assign(Y=2*frame.Y+1)})
            if node == uid(2):
                return SimpleNamespace(tables={'Data': frame.copy()})
            return SimpleNamespace(tables={'Fit': pd.DataFrame({'Slope': [np.polyfit(frame.X, frame.Y, 1)[0]]})})

        for value in (3., 4.):
            calls.clear()
            raw.loc[1, 'Y'] = value
            outcomes = evaluate_graph(graph, graph.affected([uid(1)]), {uid(1): raw}, {}, compute)
            slope = outcomes[uid(3)].result.tables['Fit'].Slope.iloc[0]
            self.assertAlmostEqual(slope, np.polyfit(raw.X, 2*raw.Y+1, 1)[0])
            self.assertEqual(len(calls), len(set(calls)))
            self.assertNotIn(uid(5), calls)
            self.assertTrue(all(item.error is None for item in outcomes.values()))

    def test_parent_failure_blocks_descendants_but_not_an_independent_branch(self):
        graph = self.graph()
        calls = []

        def compute(node, frame):
            calls.append(node)
            if node == uid(2):
                raise ValueError('invalid reference')
            return SimpleNamespace(tables={'Data': frame.copy()})

        outcomes = evaluate_graph(graph, graph.affected([uid(1)]),
                                  {uid(1): pd.DataFrame({'X': [1.]})}, {}, compute)
        self.assertNotIn(uid(3), calls)
        self.assertIn('invalid reference', str(outcomes[uid(3)].error))
        self.assertIsNone(outcomes[uid(4)].error)

    def test_cancellation_does_not_publish_a_partial_batch(self):
        from threading import Event
        graph = self.graph()
        cancel = Event()

        def compute(node, frame):
            cancel.set()
            return SimpleNamespace(tables={'Data': frame})

        with self.assertRaises(ChainCancelled):
            evaluate_graph(graph, graph.affected([uid(1)]),
                           {uid(1): pd.DataFrame({'X': [1.]})}, {}, compute, cancel=cancel)
