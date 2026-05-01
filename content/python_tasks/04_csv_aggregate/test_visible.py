from solution import csv_aggregate


def test_basic_aggregation():
    text = "category,count\nfruit,10\nveg,3\nfruit,5\n"
    assert csv_aggregate(text) == {"fruit": 15, "veg": 3}


def test_filter_empty_category():
    text = "category,count\nfruit,10\n,2\nfruit,5\n"
    assert csv_aggregate(text) == {"fruit": 15}


def test_filter_non_numeric_count():
    text = "category,count\nfruit,10\nveg,abc\nfruit,5\n"
    assert csv_aggregate(text) == {"fruit": 15}


def test_sort_count_desc_then_alpha():
    text = "category,count\nb,5\na,5\nc,10\n"
    out = csv_aggregate(text)
    assert list(out.items()) == [("c", 10), ("a", 5), ("b", 5)]


def test_empty_input():
    assert csv_aggregate("") == {}
    assert csv_aggregate("category,count\n") == {}
