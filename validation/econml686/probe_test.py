"""Synthetic tests exercising the installed pytest/xdist dependency path."""
import pytest


@pytest.mark.parametrize('value', range(4))
def test_worker_probe(value):
    assert value * value >= 0
