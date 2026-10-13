"""Focused acceptance and service tests."""

from functools import wraps
from unittest import SkipTest


def with_original_code(test):
    """Keep retained game code out of fixtures; opt in with test.py --retail-exe."""
    @wraps(test)
    def run(*args, **kwargs):
        import original_inputs
        if original_inputs._original is None:
            raise SkipTest('Supply --retail-exe to test locally extracted routines')
        return test(*args, **kwargs)
    return run
