import re
from collections.abc import Collection
from dataclasses import dataclass

from rapidfuzz.distance import Levenshtein

DIGIT_TO_ALPHA: dict[str, str] = {"0": "O", "1": "I", "8": "B"}
ALPHA_TO_DIGIT: dict[str, str] = {v: k for k, v in DIGIT_TO_ALPHA.items()}


@dataclass
class RegionRules:
    target_type: str
    region: str
    digit_pos: Collection[int]
    alpha_pos: Collection[int]
    valid_re: re.Pattern[str]

    @property
    def length(self) -> int:
        return len(self.digit_pos) + len(self.alpha_pos)


RULES: dict[str, RegionRules] = {
    # UK current-format plate: AA99AAA  (2001+, ~95% of plates in use, since Sept 2001)
    # https://assets.publishing.service.gov.uk/media/6694e379fc8e12ac3edafc60/inf104-vehicle-registration-numbers-and-number-plates.pdf
    "UK_2001": RegionRules("plate", "UK", {2, 3}, {0, 1, 4, 5, 6}, re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{3}$")),
    "ITALY_1999": RegionRules("plate", "IT", {2, 3, 4}, {0, 1, 5, 6}, re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{3}$")),
    "FRANCE_2001": RegionRules("plate", "FR", {2, 3, 4}, {0, 1, 5, 6}, re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{3}$")),
}


class Normalizer:
    def __init__(self, target_type: str | None = None, region: str | None = None) -> None:
        self.target_type: str | None = target_type
        self.region: str | None = region

    def _digit_swapped(self, plate: str, digit_pos: Collection[int], alpha_pos: Collection[int]) -> str | None:
        """Return OCR-confusable single-swap variants of a string.

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
            if i in digit_pos and ch in ALPHA_TO_DIGIT:
                swap = ALPHA_TO_DIGIT[ch]
            elif i in alpha_pos and ch in DIGIT_TO_ALPHA:
                swap = DIGIT_TO_ALPHA[ch]
            if swap is not None:
                chars[i] = swap
                swaps += 1
        if swaps > 0:
            return "".join(chars)
        return None

    def normalize(self, target: str) -> str | None:
        """Return a corrected plate if I/1 or O/0 substitutions (position-aware) yield a valid plate."""
        plate = target.upper()
        for rule in RULES.values():
            if (
                rule.target_type == self.target_type
                and rule.region == self.region
                and len(plate) == rule.length
                and not rule.valid_re.match(plate)
            ):
                # only 1 alternative so far
                alt = self._digit_swapped(plate, digit_pos=rule.digit_pos, alpha_pos=rule.alpha_pos)
                if alt:
                    # may not be a valid plate, but partial correction may support a subsequent different style of correction
                    return alt
        return None


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
