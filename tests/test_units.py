import pytest

from serpentine.utils.units import convert, format_length, parse_length


def test_parse_plain_numbers():
    assert parse_length("12", "mm") == 12
    assert parse_length("-3.5", "m") == -3.5
    assert parse_length(".5", "mm") == 0.5
    assert parse_length("nonsense", "mm") is None
    assert parse_length("", "mm") is None


def test_parse_suffixed():
    assert parse_length("25.4mm", "in") == pytest.approx(1.0)
    assert parse_length("1in", "mm") == pytest.approx(25.4)
    assert parse_length('2"', "mm") == pytest.approx(50.8)
    assert parse_length("30cm", "mm") == pytest.approx(300)
    assert parse_length("2m", "cm") == pytest.approx(200)
    assert parse_length("1.5ft", "in") == pytest.approx(18)


def test_parse_feet_inches():
    assert parse_length("3'", "ft") == pytest.approx(3.0)
    assert parse_length("3'6\"", "ft") == pytest.approx(3.5)
    assert parse_length("3'-6\"", "ft") == pytest.approx(3.5)
    assert parse_length("3' 6\"", "in") == pytest.approx(42)
    assert parse_length("3'-6 1/2\"", "in") == pytest.approx(42.5)
    assert parse_length("0'9\"", "mm") == pytest.approx(228.6)
    assert parse_length("-2'6\"", "ft") == pytest.approx(-2.5)
    assert parse_length("10'", "mm") == pytest.approx(3048)


def test_parse_inch_fractions():
    assert parse_length('1/2"', "in") == pytest.approx(0.5)
    assert parse_length('6 1/2"', "in") == pytest.approx(6.5)
    assert parse_length('3 3/8"', "mm") == pytest.approx(85.725)


def test_format_metric():
    assert format_length(123.456, "mm") == "123.456 mm"
    assert format_length(1234.5678, "mm", precision=2) == "1234.57 mm"
    assert format_length(2.5, "m") == "2.5 m"
    assert format_length(0, "mm") == "0 mm"


def test_format_inches():
    assert format_length(5.25, "in") == '5.25"'


def test_format_feet_inches():
    assert format_length(3.5, "ft") == "3'-6\""
    assert format_length(3.0, "ft") == "3'-0\""
    assert format_length(3.5417, "ft") == "3'-6 1/2\""
    assert format_length(-2.5, "ft") == "-2'-6\""
    assert format_length(1.0 / 12 / 16, "ft") == "0'-0 1/16\""


def test_roundtrip():
    for text, units in [("3'-6 1/2\"", "ft"), ("42.5in", "in"),
                        ("1079.5mm", "mm")]:
        v = parse_length(text, units)
        assert parse_length(format_length(v, units), units) == \
            pytest.approx(v, abs=1e-6)


def test_convert():
    assert convert(1, "ft", "in") == pytest.approx(12)
    assert convert(1000, "mm", "m") == pytest.approx(1)
