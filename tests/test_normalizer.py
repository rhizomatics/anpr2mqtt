import datetime as dt

from anpr2mqtt.handler_common import correct_against_good_read
from anpr2mqtt.normalizers import Normalizer


def test_normalise_uk_plate_already_valid() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("AB12CDE") is None


def test_normalise_uk_plate_digit_i_corrected() -> None:
    # Position 2 is I → should become 1
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("ABI2CDE") == "AB12CDE"


def test_normalise_uk_plate_digit_o_corrected() -> None:
    # Position 3 is O → should become 0
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("AB1OCDE") == "AB10CDE"


def test_normalise_uk_plate_letter_1_corrected() -> None:
    # Position 0 is 1 → should become I
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("1B12CDE") == "IB12CDE"


def test_normalise_uk_plate_letter_0_corrected() -> None:
    # Position 0 is 0 → should become O
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("0B12CDE") == "OB12CDE"


def test_normalise_uk_plate_multiple_corrections() -> None:
    # 1→I at pos 0, I→1 at pos 2 → "IB12CDE"
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("1BI2CDE") == "IB12CDE"


def test_normalise_uk_plate_wrong_length() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("AB12CD") is None
    assert uut.normalize("AB12CDEX") is None


def test_normalise_uk_plate_no_fix_possible() -> None:
    # No single I/1/O/0 swap makes this valid
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("XXXXXXX") is None


def test_normalise_uk_plate_lowercase_input() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("abi2cde") == "AB12CDE"


def test_digit_swapped_swaps_digit_1_to_i() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("XPI9TCY") == "XP19TCY"


def test_digit_swapped_swaps_digit_0_to_o() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("AB1OCDE") == "AB10CDE"


def test_digit_swapped_swaps_letter_i_to_1() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("1B12CDE") == "IB12CDE"


def test_digit_swapped_swaps_letter_o_to_0() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("0B12CDE") == "OB12CDE"


def test_digit_swapped_no_swappable_chars() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    # "AB23CDE": no I, O, 1, or 0 → no alternatives
    assert uut.normalize("AB23CDE") is None


def test_digit_swapped_wrong_length() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("AB12CD") is None


def test_digit_swapped_multiple_swappable_positions() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    assert uut.normalize("1BIOCD8") == "IB10CDB"


def test_correct_via_alternative_not_direct_fuzzy_match() -> None:
    uut = Normalizer(target_type="plate", region="UK")
    cached = ("SP19TCY", dt.datetime.now(dt.UTC))
    # Without normalizer, distance("SPISTCY", "SP19TCY") = 2 → no correction at tolerance=1
    assert correct_against_good_read("SPISTCY", cached, ttl=60, tolerance=1) == "SPISTCY"
    # With normalizer, "SPI9TCY" alternative is distance 1 from "SPISTCY" → corrected
    assert correct_against_good_read("SPISTCY", cached, ttl=60, tolerance=1, normalizer=uut) == "SP19TCY"
