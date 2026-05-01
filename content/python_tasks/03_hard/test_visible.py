import pytest
from solution import CycleError, TaskScheduler


def test_simple_chain():
    s = TaskScheduler()
    s.add("build", ["compile"])
    s.add("compile", ["lint"])
    s.add("lint")
    assert s.run_order() == ["lint", "compile", "build"]


def test_cycle_two_nodes():
    s = TaskScheduler()
    s.add("a", ["b"])
    s.add("b", ["a"])
    with pytest.raises(CycleError):
        s.run_order()


def test_alphabetical_tiebreak():
    s = TaskScheduler()
    s.add("z")
    s.add("a")
    s.add("m")
    assert s.run_order() == ["a", "m", "z"]
