import re
from abc import abstractmethod


class Normalizer:
    def __init__(self, target_type: str | None = None, region: str | None = None) -> None:
        self.target_type: str | None = target_type
        self.region: str | None = region

    @abstractmethod
    def normalize(self, target: str) -> str | None:
        pass


class UkPlateNormalizer(Normalizer):
    # UK current-format plate: AA99AAA  (2001+, ~95% of plates in use)
    _UK_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{3}$")
    _UK_DIGIT_POS = frozenset({2, 3})
    _UK_LETTER_POS = frozenset({0, 1, 4, 5, 6})

    def __init__(self) -> None:
        super().__init__("plate", "UK")
        self.target_type = "plate"

    def normalize(self, target: str) -> str | None:
        """Return a corrected plate if I/1 or O/0 substitutions (position-aware) yield a valid AA99AAA plate.

        This is not the only UK plate format, however it is by far the most common
        Returns None when the plate is already valid or cannot be fixed by these substitutions alone.
        """
        plate = target.upper()
        if len(plate) != 7:
            return None
        if UkPlateNormalizer._UK_PLATE_RE.match(plate):
            return None
        chars = list(plate)
        for i, ch in enumerate(chars):
            if i in UkPlateNormalizer._UK_LETTER_POS:
                if ch == "1":
                    chars[i] = "I"
                elif ch == "0":
                    chars[i] = "O"
            elif i in UkPlateNormalizer._UK_DIGIT_POS:
                if ch == "I":
                    chars[i] = "1"
                elif ch == "O":
                    chars[i] = "0"
        candidate = "".join(chars)
        return candidate if UkPlateNormalizer._UK_PLATE_RE.match(candidate) else None


NORMALIZERS: dict[str, dict[str, type[Normalizer]]] = {"plate": {"UK": UkPlateNormalizer}}
