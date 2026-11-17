"""Normal-probability axes with ticks expressed in fractions or percentages."""
from matplotlib.scale import ScaleBase, register_scale
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter, NullLocator
from matplotlib.transforms import Transform
import numpy as np
from scipy.special import ndtr, ndtri


FRACTION_SCALE = "probability"
PERCENT_SCALE = "probability %"
PROBABILITY_SCALES = {FRACTION_SCALE: 1., PERCENT_SCALE: 100.}
_TICKS = np.array([.001, .005, .01, .02, .05, .1, .2, .3, .5, .7, .8, .9, .95, .98, .99, .995, .999])


class _NormalQuantile(Transform):
    input_dims = output_dims = 1
    is_separable = True
    has_inverse = True

    def __init__(self, divisor, inverse=False):
        super().__init__()
        self.divisor = divisor
        self.inverse = inverse

    def transform_non_affine(self, values):
        values = np.asarray(values, dtype=float)
        if self.inverse:
            return ndtr(values) * self.divisor
        relative = values / self.divisor
        return ndtri(np.where((relative > 0) & (relative < 1), relative, np.nan))

    def inverted(self):
        return _NormalQuantile(self.divisor, not self.inverse)


class _Probability(ScaleBase):
    name = FRACTION_SCALE
    divisor = PROBABILITY_SCALES[name]

    def get_transform(self):
        return _NormalQuantile(self.divisor)

    def set_default_locators_and_formatters(self, axis):
        axis.set_major_locator(FixedLocator(_TICKS * self.divisor))
        axis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
        axis.set_minor_locator(NullLocator())
        axis.set_minor_formatter(NullFormatter())

    def limit_range_for_scale(self, vmin, vmax, minpos):
        low, high = .0001 * self.divisor, .9999 * self.divisor
        vmin = vmin if 0 < vmin < self.divisor else low
        vmax = vmax if 0 < vmax < self.divisor else high
        return (vmin, vmax) if vmin < vmax else (low, high)


class _ProbabilityPercent(_Probability):
    name = PERCENT_SCALE
    divisor = PROBABILITY_SCALES[name]


register_scale(_Probability)
register_scale(_ProbabilityPercent)
