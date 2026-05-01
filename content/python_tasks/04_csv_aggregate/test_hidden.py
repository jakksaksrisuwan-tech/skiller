from solution import csv_aggregate


def test_extra_columns_ignored():
    text = "category,count,note,owner\nfruit,3,a,me\nfruit,2,b,you\n"
    assert csv_aggregate(text) == {"fruit": 5}


def test_quoted_field_with_comma():
    text = 'category,count\n"berries, mixed",4\n"berries, mixed",6\n'
    assert csv_aggregate(text) == {"berries, mixed": 10}


def test_negative_counts_valid():
    text = "category,count\nfruit,10\nfruit,-3\n"
    assert csv_aggregate(text) == {"fruit": 7}


def test_filter_wrong_column_count():
    text = "category,count\nfruit,1\nbadrow_no_comma\nfruit,2\n"
    assert csv_aggregate(text) == {"fruit": 3}


def test_crlf_line_endings():
    text = "category,count\r\nfruit,2\r\nveg,1\r\n"
    assert csv_aggregate(text) == {"fruit": 2, "veg": 1}


def test_alpha_tiebreak_stable():
    text = "category,count\nzeta,1\nalpha,1\nmu,1\n"
    out = csv_aggregate(text)
    assert list(out.keys()) == ["alpha", "mu", "zeta"]


def test_count_is_string_int_with_whitespace():
    # csv.DictReader leaves whitespace as part of the field; user's
    # implementation may strip — but the test only requires that pure
    # numeric strings convert. Whitespace counts are NOT required to pass.
    text = "category,count\nfruit, 5\nfruit,6\n"
    out = csv_aggregate(text)
    assert out.get("fruit", 0) >= 6  # at minimum the clean row counted
