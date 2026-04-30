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
