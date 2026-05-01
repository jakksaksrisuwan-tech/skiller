from solution import sum_even


def test_basic():
    assert sum_even([1, 2, 3, 4]) == 6


def test_empty():
    assert sum_even([]) == 0


def test_all_odd():
    assert sum_even([1, 3, 5]) == 0


def test_negatives():
    assert sum_even([-2, -1, 0]) == -2
