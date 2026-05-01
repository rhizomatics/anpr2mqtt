import datetime as dt

from anpr2mqtt.handler_common import correct_against_good_read
from anpr2mqtt.normalizers import UkPlateNormalizer


def test_normalise_uk_plate_already_valid() -> None:
    uut = UkPlateNormalizer()
    assert uut.normalize("AB12CDE") is None


def test_normalise_uk_plate_digit_i_corrected() -> None:
    # Position 2 is I → should become 1
    uut = UkPlateNormalizer()
    assert uut.normalize("ABI2CDE") == "AB12CDE"


def test_normalise_uk_plate_digit_o_corrected() -> None:
    # Position 3 is O → should become 0
    uut = UkPlateNormalizer()
    assert uut.normalize("AB1OCDE") == "AB10CDE"


def test_normalise_uk_plate_letter_1_corrected() -> None:
    # Position 0 is 1 → should become I
    uut = UkPlateNormalizer()
    assert uut.normalize("1B12CDE") == "IB12CDE"


def test_normalise_uk_plate_letter_0_corrected() -> None:
    # Position 0 is 0 → should become O
    uut = UkPlateNormalizer()
    assert uut.normalize("0B12CDE") == "OB12CDE"


def test_normalise_uk_plate_multiple_corrections() -> None:
    # 1→I at pos 0, I→1 at pos 2 → "IB12CDE"
    uut = UkPlateNormalizer()
    assert uut.normalize("1BI2CDE") == "IB12CDE"


def test_normalise_uk_plate_wrong_length() -> None:
    uut = UkPlateNormalizer()
    assert uut.normalize("AB12CD") is None
    assert uut.normalize("AB12CDEX") is None


def test_normalise_uk_plate_no_fix_possible() -> None:
    # No single I/1/O/0 swap makes this valid
    uut = UkPlateNormalizer()
    assert uut.normalize("XXXXXXX") is None


def test_normalise_uk_plate_lowercase_input() -> None:
    uut = UkPlateNormalizer()
    assert uut.normalize("abi2cde") == "AB12CDE"


# --- alternatives ---


def test_digit_swapped_swaps_digit_1_to_i() -> None:
    uut = UkPlateNormalizer()
    assert uut.digit_swapped("XPI9TCY") == "XP19TCY"


def test_digit_swapped_swaps_digit_0_to_o() -> None:
    uut = UkPlateNormalizer()
    assert uut.digit_swapped("AB1OCDE") == "AB10CDE"


def test_alternatives_swaps_letter_i_to_1() -> None:
    uut = UkPlateNormalizer()
    assert uut.digit_swapped("1B12CDE") == "IB12CDE"


def test_alternatives_swaps_letter_o_to_0() -> None:
    uut = UkPlateNormalizer()
    assert uut.digit_swapped("0B12CDE") == "OB12CDE"


def test_alternatives_no_swappable_chars() -> None:
    uut = UkPlateNormalizer()
    # "AB23CDE": no I, O, 1, or 0 → no alternatives
    assert uut.digit_swapped("AB23CDE") is None


def test_alternatives_wrong_length() -> None:
    uut = UkPlateNormalizer()
    assert uut.digit_swapped("AB12CD") is None


def test_alternatives_multiple_swappable_positions() -> None:
    uut = UkPlateNormalizer()
    # "IB10CDE": pos 0 = 'I'→'1', pos 2 = '1'→'I', pos 3 = '0'→'O' → three alternatives
    assert uut.digit_swapped("1BIOCD8") == "IB10CDB"


# --- correct_against_good_read with normalizer alternatives ---


def test_correct_via_alternative_not_direct_fuzzy_match() -> None:
    uut = UkPlateNormalizer()
    cached = ("SP19TCY", dt.datetime.now(dt.UTC))
    # Without normalizer, distance("SPISTCY", "SP19TCY") = 2 → no correction at tolerance=1
    assert correct_against_good_read("SPISTCY", cached, ttl=60, tolerance=1) == "SPISTCY"
    # With normalizer, "SPI9TCY" alternative is distance 1 from "SPISTCY" → corrected
    assert correct_against_good_read("SPISTCY", cached, ttl=60, tolerance=1, normalizer=uut) == "SP19TCY"
