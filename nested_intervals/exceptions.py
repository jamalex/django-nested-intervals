"""
Nested Interval exceptions.
"""
from __future__ import unicode_literals


class InvalidMove(Exception):
    """
    An invalid node move was attempted.

    For example, attempting to make a node a child of itself.
    """
    pass


class IntervalTooSmall(Exception):
    """
    The interval sizes resulting from an insertion would be too small to represent
    given the current number of decimal places. The calling code will need to rebalance.
    """