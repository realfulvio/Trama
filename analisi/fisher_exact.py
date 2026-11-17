"""Exact fixed-margin probability ordering for general contingency tables."""

from functools import lru_cache
from itertools import accumulate
from math import comb


_MAX_TOTAL = 2000
_MAX_AXIS = 12
_MAX_WORK = 3_000_000


class FisherWorkLimit(ValueError):
    """The exact search would exceed the interactive analysis budget."""


def fisher_exact_rxc(table):
    """Return the integer tail mass, normalizer and number of fixed-margin tables.

    A table's weight is the product of its row multinomial coefficients. The
    normalizer is the multinomial coefficient of the column totals. Integer
    comparison includes all ties, regardless of floating-point rounding.
    """
    if max(table.shape) > _MAX_AXIS or int(table.sum()) > _MAX_TOTAL:
        raise FisherWorkLimit
    row_totals = tuple(sorted(map(int, table.sum(axis=1))))
    column_totals = tuple(sorted(map(int, table.sum(axis=0))))
    # Canonical orientation keeps the same work budget after transposition.
    if (len(column_totals), column_totals) > (len(row_totals), row_totals):
        table = table.T
    rows = sorted((tuple(map(int, row)) for row in table), key=sum)
    totals = tuple(map(sum, zip(*rows, strict=True)))
    order = sorted(range(len(totals)), key=totals.__getitem__)
    capacities = tuple(totals[index] for index in order)
    rows = [tuple(row[index] for index in order) for row in rows]
    row_sums = [sum(row) for row in rows]
    last = len(rows) - 1
    columns = len(capacities)
    work = 0
    choose = lru_cache(maxsize=8192)(comb)

    @lru_cache(maxsize=8192)
    def multinomial(counts):
        weight = 1
        remaining = sum(counts)
        for count in counts[:-1]:
            weight *= choose(remaining, count)
            remaining -= count
        return weight

    observed = 1
    for row in rows:
        observed *= multinomial(row)

    def allocations(remaining, row_sum):
        # The last column is forced. Earlier columns can take only counts
        # that leave enough capacity in the suffix for the rest of the row.
        suffix = tuple(reversed(tuple(accumulate(reversed(remaining)))))
        next_margins = list(remaining)

        def distribute(index, count, weight):
            nonlocal work
            if index == columns - 1:
                next_margins[index] = remaining[index] - count
                yield tuple(next_margins), weight
                return
            low = max(0, count - suffix[index + 1])
            high = min(count, remaining[index])
            for used in range(low, high + 1):
                work += 1
                if work > _MAX_WORK:
                    raise FisherWorkLimit
                next_margins[index] = remaining[index] - used
                yield from distribute(index + 1, count - used, weight * choose(count, used))

        yield from distribute(0, row_sum, 1)

    @lru_cache(maxsize=8192)
    def bounds(index, remaining):
        if index == last:
            weight = multinomial(remaining)
            return weight, weight, 1
        minimum = maximum = count = 0
        for next_margins, weight in allocations(remaining, row_sums[index]):
            low, high, leaves = bounds(index + 1, next_margins)
            minimum = min(minimum, weight * low) if minimum else weight * low
            maximum = max(maximum, weight * high)
            count += leaves
        return minimum, maximum, count

    def tail(index, remaining, limit):
        low, high, _ = bounds(index, remaining)
        if high <= limit:
            return multinomial(remaining)
        if low > limit:
            return 0
        return sum(weight * tail(index + 1, next_margins, limit // weight)
                   for next_margins, weight in allocations(remaining, row_sums[index]))

    try:
        _, _, table_count = bounds(0, capacities)
        return tail(0, capacities, observed), multinomial(capacities), table_count
    finally:
        bounds.cache_clear()
        multinomial.cache_clear()
        choose.cache_clear()
