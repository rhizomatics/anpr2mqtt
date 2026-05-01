import re
from abc import abstractmethod

from rapidfuzz.distance import Levenshtein

DIGIT_TO_ALPHA: dict[str, str] = {"0": "O", "1": "I", "8": "B"}
ALPHA_TO_DIGIT: dict[str, str] = {v: k for k, v in DIGIT_TO_ALPHA.items()}


class Normalizer:
    def __init__(self, target_type: str | None = None, region: str | None = None) -> None:
        self.target_type: str | None = target_type
        self.region: str | None = region

    @abstractmethod
    def normalize(self, target: str) -> str | None:
        pass

    @abstractmethod
    def digit_swapped(self, plate: str) -> str | None:
        """Return OCR-confusable variants of a (valid) plate for use in fuzzy correction.

        Subclasses override this to generate position-aware character swaps so that
        a misread can be matched even when it differs in ways the normalizer cannot
        fully repair on its own (e.g. '9' read as 'S').
        """
        return None


class UkPlateNormalizer(Normalizer):
    # UK current-format plate: AA99AAA  (2001+, ~95% of plates in use, since Sept 2001)

    # https://assets.publishing.service.gov.uk/media/6694e379fc8e12ac3edafc60/inf104-vehicle-registration-numbers-and-number-plates.pdf
    _UK_COMMON_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{3}$")
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
        if UkPlateNormalizer._UK_COMMON_PLATE_RE.match(plate):
            return None
        return self.digit_swapped(plate)

    def digit_swapped(self, plate: str) -> str | None:
        """Return OCR-confusable single-swap variants of a valid UK plate.

        Reverses the I/1 and O/0 substitution rules so that a misread which the
        normalizer cannot fully repair (e.g. '9' seen as 'S') can still be caught
        by fuzzy matching against a variant that differs by only one edit.
        """
        plate = plate.upper()
        if len(plate) != 7:
            return None

        chars = list(plate)
        swaps: int = 0
        for i, ch in enumerate(chars):
            swap: str | None = None
            if i in UkPlateNormalizer._UK_DIGIT_POS and ch in ALPHA_TO_DIGIT:
                swap = ALPHA_TO_DIGIT[ch]
            elif i in UkPlateNormalizer._UK_LETTER_POS and ch in DIGIT_TO_ALPHA:
                swap = DIGIT_TO_ALPHA[ch]
            if swap is not None:
                chars[i] = swap
                swaps += 1
        if swaps > 0:
            return "".join(chars)
        return None


NORMALIZERS: dict[str, dict[str, type[Normalizer]]] = {"plate": {"UK": UkPlateNormalizer}}


def fuzzy_match(target_id: str, max_dist: int, candidates: list[str]) -> str | None:
    """Return the closest key in candidates within max_dist edits, or None."""
    best: str | None = None
    best_dist = max_dist + 1
    for candidate in candidates:
        d = Levenshtein.distance(target_id, candidate)
        if d < best_dist:
            best_dist = d
            best = candidate
    return best if best_dist <= max_dist else None
