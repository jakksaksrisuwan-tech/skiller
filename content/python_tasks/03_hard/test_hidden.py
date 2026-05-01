import pytest
from solution import CycleError, TaskScheduler


def test_implicit_dep_added():
    s = TaskScheduler()
    s.add("a", ["b"])  # b never explicitly added
    assert s.run_order() == ["b", "a"]


def test_idempotent_readd_merges_deps():
    s = TaskScheduler()
    s.add("a", ["b"])
    s.add("a", ["c"])
    s.add("b")
    s.add("c")
    order = s.run_order()
    assert order.index("b") < order.index("a")
    assert order.index("c") < order.index("a")
    assert set(order) == {"a", "b", "c"}


def test_multi_component():
    s = TaskScheduler()
    s.add("x", ["y"])
    s.add("y")
    s.add("p", ["q"])
    s.add("q")
    order = s.run_order()
    assert order.index("y") < order.index("x")
    assert order.index("q") < order.index("p")


def test_self_dependency_is_cycle():
    s = TaskScheduler()
    s.add("x", ["x"])
    with pytest.raises(CycleError):
        s.run_order()


def test_three_node_cycle():
    s = TaskScheduler()
    s.add("a", ["b"])
    s.add("b", ["c"])
    s.add("c", ["a"])
    with pytest.raises(CycleError) as exc:
        s.run_order()
    text = str(exc.value)
    # cycle nodes mentioned
    assert sum(n in text for n in ("a", "b", "c")) >= 2


def test_diamond():
    s = TaskScheduler()
    s.add("d", ["b", "c"])
    s.add("b", ["a"])
    s.add("c", ["a"])
    s.add("a")
    order = s.run_order()
    assert order[0] == "a"
    assert order[-1] == "d"
    assert set(order[1:3]) == {"b", "c"}


def test_alphabetical_in_layer():
    s = TaskScheduler()
    # all roots — should sort alphabetically
    for name in ["beta", "alpha", "gamma"]:
        s.add(name)
    assert s.run_order() == ["alpha", "beta", "gamma"]


def test_empty_scheduler():
    assert TaskScheduler().run_order() == []
