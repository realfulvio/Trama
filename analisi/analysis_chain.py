"""Persistent result-input identities and iterative analysis dependency evaluation."""
from collections import deque
from dataclasses import dataclass
import heapq
from uuid import UUID

import pandas as pd


# This is the existing project's theoretical 256 tables x 256 recipes budget,
# shared across a linked project rather than imposing a separate depth limit.
MAX_ANALYSIS_NODES = 65_536
RESULT_CONTEXT = "trama_result_context"


def valid_analysis_id(value):
    try:
        valid = isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("Invalid persistent analysis identity.")
    return value


@dataclass(frozen=True)
class ResultSource:
    analysis_id: str
    table: str

    def __post_init__(self):
        valid_analysis_id(self.analysis_id)
        if not isinstance(self.table, str) or not self.table or len(self.table) > 1024:
            raise ValueError("Invalid source result table name.")


class ChainCancelled(Exception):
    """A candidate batch must not be published after cancellation."""


class SourceUnavailable(ValueError):
    def __init__(self, source, reason):
        self.source = source
        # Preserve the original cause without growing a prefix for every level.
        self.reason = reason.reason if isinstance(reason, SourceUnavailable) else str(reason)
        super().__init__(f'Source results are unavailable: {self.reason}')


@dataclass(frozen=True)
class Outcome:
    result: object = None
    error: Exception | None = None


class AnalysisGraph:
    def __init__(self, nodes, *, dependencies=None):
        self.sources = {}
        for identifier, source in nodes:
            valid_analysis_id(identifier)
            if identifier in self.sources:
                raise ValueError("Duplicate persistent analysis identity.")
            if source is not None and not isinstance(source, ResultSource):
                raise ValueError("Invalid analysis result source.")
            self.sources[identifier] = source
        if len(self.sources) > MAX_ANALYSIS_NODES:
            raise ValueError("The project exceeds the analysis dependency budget.")
        self.parents = {}
        self.children = {identifier: [] for identifier in self.sources}
        dependencies = dependencies or {}
        for identifier, source in self.sources.items():
            parents = list(dict.fromkeys(([source.analysis_id] if source else []) +
                                          list(dependencies.get(identifier, ()))))
            if any(parent not in self.sources for parent in parents):
                raise ValueError("An analysis refers to a missing source analysis.")
            self.parents[identifier] = tuple(parents)
            for parent in parents:
                self.children[parent].append(identifier)
        positions = {identifier: index for index, identifier in enumerate(self.sources)}
        remaining = {identifier: len(parents) for identifier, parents in self.parents.items()}
        ready = [(positions[identifier], identifier) for identifier, count in remaining.items() if count == 0]
        heapq.heapify(ready)
        self.order = []
        while ready:
            _, identifier = heapq.heappop(ready)
            self.order.append(identifier)
            for child in self.children[identifier]:
                remaining[child] -= 1
                if remaining[child] == 0:
                    heapq.heappush(ready, (positions[child], child))
        if len(self.order) != len(self.sources):
            raise ValueError("Analysis input links contain a cycle.")

    def affected(self, seeds, *, unavailable=()):
        unavailable = set(unavailable)
        selected, pending = set(), deque(seeds)
        while pending:
            identifier = pending.popleft()
            if identifier not in self.sources:
                raise ValueError("Unknown analysis in dependency request.")
            if identifier in selected:
                continue
            selected.add(identifier)
            pending.extend(self.children[identifier])
            pending.extend(parent for parent in self.parents[identifier] if parent in unavailable)
        return [identifier for identifier in self.order if identifier in selected]


def result_frame(result, table, *, max_cells=2_000_000):
    """Materialize a read-only result's table as an independent input snapshot."""
    if result is None or table not in result.tables:
        raise ValueError(f'The source analysis no longer provides result table "{table}".')
    original = result.tables[table]
    if original.empty or original.columns.empty:
        raise ValueError(f'The source result table "{table}" is empty.')
    if original.size > max_cells:
        raise ValueError("The source result table exceeds the input size limit.")
    frame = original.copy(deep=True)
    if not isinstance(frame.index, pd.RangeIndex):
        labels, columns, names = frame.index, set(frame.columns), []
        for level, title in enumerate(labels.names, 1):
            column = title or ("Label" if labels.nlevels == 1 else f"Level {level}")
            while column in columns:
                column += " (index)"
            columns.add(column)
            names.append(column)
        if isinstance(labels, pd.MultiIndex):
            frame = frame.reset_index(names=names)
        else:
            frame = frame.set_axis(pd.Index(
                [str(value) if isinstance(value, tuple) else value for value in labels],
                name=names[0], tupleize_cols=False)).reset_index()
    frame = frame.rename(columns=str)
    if not frame.columns.is_unique:
        raise ValueError("The source result has ambiguous column names.")
    if frame.size > max_cells:
        raise ValueError("The source result table exceeds the input size limit.")
    context = getattr(result, "table_contexts", {}).get(table)
    if context is not None:
        frame.attrs[RESULT_CONTEXT] = context
    return frame


def evaluate_graph(graph, selected, inputs, cached, compute, *, cancel=None, progress=None, on_result=None):
    """Compute without mutating runs, source frames, or confirmed results."""
    selected = list(selected)
    outcomes = {}
    available = dict(cached)
    for position, identifier in enumerate(selected):
        if cancel is not None and cancel.is_set():
            raise ChainCancelled
        source = graph.sources[identifier]
        try:
            for parent in graph.parents[identifier]:
                previous = outcomes.get(parent)
                if previous is not None and previous.error is not None:
                    raise SourceUnavailable(source, previous.error)
                if available.get(parent) is None:
                    raise SourceUnavailable(source, "The source analysis has not been calculated.")
            frame = result_frame(available.get(source.analysis_id), source.table) if source else inputs[identifier]
            result = compute(identifier, frame)
            available[identifier] = result
            outcomes[identifier] = Outcome(result=result)
            if on_result is not None:
                on_result(identifier, result)
        except ChainCancelled:
            raise
        except Exception as error:
            available.pop(identifier, None)
            outcomes[identifier] = Outcome(error=error)
        if progress is not None:
            progress(position + 1, len(selected))
    if cancel is not None and cancel.is_set():
        raise ChainCancelled
    return outcomes
