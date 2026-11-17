"""Independent sRGB and tick oracles for the 0.72 heat-map fixtures; standard library only."""
from decimal import Decimal, ROUND_FLOOR
import math


def rgba(color, opacity=1.0):
    text = color.removeprefix('#')
    if len(text) == 6:
        text += 'ff'
    if len(text) != 8:
        raise ValueError('Oracle fixtures use hexadecimal RGB/RGBA colors.')
    values = tuple(int(text[i:i + 2], 16) / 255 for i in range(0, 8, 2))
    return (*values[:3], values[3] * opacity)


def interpolate(a, b, position):
    t = Decimal(str(position))
    return tuple(float(Decimal(str(x)) + t * (Decimal(str(y)) - Decimal(str(x)))) for x, y in zip(a, b))


def color(value, *, low, high, minimum, maximum, midpoint=None, middle=None,
          opacity=1.0, missing='#445566', outside=None):
    if value is None or not math.isfinite(float(value)):
        return rgba(missing)
    if value < low or value > high:
        if outside:
            return rgba(outside, opacity)
        value = min(high, max(low, value))
    if middle is None:
        t = (Decimal(str(value)) - Decimal(str(low))) / (Decimal(str(high)) - Decimal(str(low)))
        return interpolate(rgba(minimum, opacity), rgba(maximum, opacity), t)
    if value <= midpoint:
        t = (Decimal(str(value)) - Decimal(str(low))) / (Decimal(str(midpoint)) - Decimal(str(low)))
        return interpolate(rgba(minimum, opacity), rgba(middle, opacity), t)
    t = (Decimal(str(value)) - Decimal(str(midpoint))) / (Decimal(str(high)) - Decimal(str(midpoint)))
    return interpolate(rgba(middle, opacity), rgba(maximum, opacity), t)


def ticks(low, high, interval, start=None, budget=200):
    low, high, step = map(lambda x: Decimal(str(x)), (low, high, interval))
    first = low if start is None else Decimal(str(start))
    if not all(x.is_finite() for x in (low, high, step, first)) or not low < high or step <= 0:
        raise ValueError('Invalid legend scale.')
    if not low <= first <= high:
        raise ValueError('Legend start must be inside the color range.')
    count = int(((high - first) / step).to_integral_value(rounding=ROUND_FLOOR)) + 1
    if count > budget:
        raise ValueError('Legend tick budget exceeded.')
    return [float(first + i * step) for i in range(count)]
