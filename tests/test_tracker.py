import datetime as dt
from pathlib import Path

from anpr2mqtt.settings import Target, TargetGroup, TargetSettings
from anpr2mqtt.tracker import Sighting, Tracker, compute_time_analysis


def test_time_analysis_no_history() -> None:
    result = compute_time_analysis([], dt.datetime(2025, 6, 2, 10, 30, tzinfo=dt.UTC))
    assert result["previous_sightings"] == 0
    assert result["last_seen"] is None
    assert result["hourly_counts"] == {}
    assert result["earliest_time"] is None
    assert result["latest_time"] is None
    assert result["within_time_range"] is None


def test_time_analysis_no_current_dt() -> None:
    sightings = ["2025-06-02T07:30:00+00:00", "2025-06-02T09:15:00+00:00"]
    result = compute_time_analysis(sightings, None)
    assert result["previous_sightings"] == 2
    assert result["last_seen"] == "2025-06-02T09:15:00+00:00"
    assert result["earliest_time"] == "07:30:00"
    assert result["latest_time"] == "09:15:00"


def test_time_analysis_hourly_counts() -> None:
    sightings = [
        "2025-06-01T08:00:00+00:00",
        "2025-06-02T08:30:00+00:00",
        "2025-06-03T14:00:00+00:00",
    ]
    result = compute_time_analysis(sightings, dt.datetime(2025, 6, 4, 8, 0, tzinfo=dt.UTC))
    assert result["hourly_counts"][8] == 2
    assert result["hourly_counts"][14] == 1
    assert sum(result["hourly_counts"].values()) == 3


def test_time_analysis_within_range() -> None:
    sightings = ["2025-06-02T07:00:00+00:00", "2025-06-02T09:00:00+00:00"]
    result = compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 8, 0, tzinfo=dt.UTC))
    assert result["earliest_time"] == "07:00:00"
    assert result["latest_time"] == "09:00:00"
    assert result["within_time_range"] is True


def test_time_analysis_outside_range() -> None:
    sightings = ["2025-06-02T07:00:00+00:00", "2025-06-02T09:00:00+00:00"]
    result = compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 22, 0, tzinfo=dt.UTC))
    assert result["within_time_range"] is False


def test_time_analysis_at_boundary() -> None:
    # Exactly at earliest or latest is within range
    sightings = ["2025-06-02T07:00:00+00:00", "2025-06-02T09:00:00+00:00"]
    at_earliest = compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 7, 0, tzinfo=dt.UTC))
    at_latest = compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 9, 0, tzinfo=dt.UTC))
    assert at_earliest["within_time_range"] is True
    assert at_latest["within_time_range"] is True


def test_time_analysis_ignores_bad_entries() -> None:
    sightings = ["2025-06-02T08:00:00+00:00", "not-a-timestamp", "also-bad"]
    result = compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 8, 0, tzinfo=dt.UTC))
    assert result["hourly_counts"][8] == 1
    assert sum(result["hourly_counts"].values()) == 1


def test_track_target_time_analysis_populated(tracker: Tracker) -> None:
    ts1 = dt.datetime(2025, 6, 1, 8, 0, tzinfo=dt.UTC)
    ts2 = dt.datetime(2025, 6, 2, 14, 0, tzinfo=dt.UTC)
    ts3 = dt.datetime(2025, 6, 3, 10, 0, tzinfo=dt.UTC)
    tracker.record("TIMETEST", "plate", ts1)
    tracker.record("TIMETEST", "plate", ts2)
    analysis = tracker.record("TIMETEST", "plate", ts3)
    assert analysis["previous_sightings"] == 2
    assert analysis["last_seen"] == ts2.isoformat()
    assert analysis["hourly_counts"][8] == 1
    assert analysis["hourly_counts"][14] == 1
    assert analysis["earliest_time"] == "08:00:00"
    assert analysis["latest_time"] == "14:00:00"
    assert analysis["within_time_range"] is True  # 10:00 is between 08:00 and 14:00


def test_track_target_new(tracker: Tracker) -> None:
    result = tracker.record("TEST123", "plate", dt.datetime(2025, 1, 1, tzinfo=dt.UTC))
    assert result["previous_sightings"] == 0
    assert result["last_seen"] is None


def test_track_target_existing(tracker: Tracker) -> None:
    ts1 = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    ts2 = dt.datetime(2025, 1, 2, tzinfo=dt.UTC)
    tracker.record("TEST456", "plate", ts1)
    result = tracker.record("TEST456", "plate", ts2)
    assert result["previous_sightings"] == 1
    assert result["last_seen"] == ts1.isoformat()


def test_track_target_no_timestamp(tracker: Tracker) -> None:
    result = tracker.record("UNKNOWN", "plate", None)
    assert result["previous_sightings"] == 0


def test_track_target_exception(tracker: Tracker, tmp_path: Path) -> None:
    """json.load raises → exception is caught and logged (lines 225-226)."""
    target_dir = tmp_path / "plate"
    target_dir.mkdir()
    bad_file = target_dir / "BADPLATE.json"
    bad_file.write_text("not valid json")
    result = tracker.record("BADPLATE", "plate", dt.datetime(2025, 1, 1, tzinfo=dt.UTC))
    assert result == {
        "earliest_time": None,
        "hourly_counts": {},
        "last_seen": None,
        "latest_time": None,
        "previous_sightings": 0,
        "within_time_range": None,
    }


def test_corrections_unknown(tracker: Tracker) -> None:
    result: Sighting = tracker.find("PK12TST")
    assert result.target.group is None
    assert result.target.id == "PK12TST"
    assert result.uncorrected == "PK12TST"
    assert result.target.priority == "high"
    assert result.target.description is None
    assert not result.ignore


def test_corrections_gangsta(tracker: Tracker) -> None:
    tracker.target_config = TargetSettings(
        groups=[
            TargetGroup(name="dangerous", priority="critical", members=[Target(id="PK12TST", description="Local dodgy man")])
        ]
    )

    result: Sighting = tracker.find("PK12TST")
    assert result.target.group == "dangerous"
    assert result.target.id == "PK12TST"
    assert result.uncorrected == "PK12TST"
    assert result.target.priority == "critical"
    assert result.target.description == "Local dodgy man"
    assert not result.ignore


def test_corrections_known(tracker: Tracker) -> None:
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="known", members=[Target(id="PK12TST", description="Postie")])]
    )

    result: Sighting = tracker.find("PK12TST")
    assert result.target.group == "known"
    assert result.target.id == "PK12TST"
    assert result.uncorrected == "PK12TST"
    assert result.target.priority == "medium"
    assert result.target.description == "Postie"
    assert not result.ignore


def test_corrections_known_with_correction(tracker: Tracker) -> None:
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="known", members=[Target(id="PK12TST", description="Postie")])],
        correction={"PK12TST": ["P12TST"]},
    )

    result: Sighting = tracker.find("P12TST")
    assert result.target.group == "known"
    assert result.target.id == "PK12TST"
    assert result.uncorrected == "P12TST"
    assert result.target.priority == "medium"
    assert result.target.description == "Postie"
    assert not result.ignore


def test_corrections_known_with_per_target_correction(tracker: Tracker) -> None:
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="known", members=[Target(id="PK12TST", description="Postie", correction=["P12TST"])])]
    )

    result: Sighting = tracker.find("P12TST")
    assert result.target.group == "known"
    assert result.target.id == "PK12TST"
    assert result.uncorrected == "P12TST"
    assert result.target.priority == "medium"
    assert result.target.description == "Postie"
    assert not result.ignore


def test_corrections_settings_takes_priority_over_per_target(tracker: Tracker) -> None:
    """TargetSettings.correction overrides Target.correction when both match."""
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="known", members=[Target(id="PK12TST", description="Postie", correction=["P12TST"])])],
        correction={"OTHER999": ["P12TST"]},
    )

    result: Sighting = tracker.find("P12TST")
    assert result.target.id == "OTHER999"


def test_corrections_ignore(tracker: Tracker) -> None:
    tracker.target_config = TargetSettings(ignore=[".*TST"])
    result: Sighting = tracker.find("PK12TST")
    assert result.target.group is None
    assert result.target.id == "PK12TST"
    assert result.uncorrected == "PK12TST"
    assert result.target.priority == "low"
    assert result.ignore


def test_classify_target_no_config(tracker: Tracker) -> None:
    tracker.target_config = None
    result: Sighting = tracker.find("AB12CDE")
    assert result.target.id == "AB12CDE"
    assert result.uncorrected == "AB12CDE"
    assert result.target.group is None


def test_classify_target_empty_target(tracker: Tracker) -> None:
    result: Sighting = tracker.find("")
    assert result.target.group is None
    assert result.target.group != "known"


def test_classify_target_dangerous_no_description(tracker: Tracker) -> None:
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="dangerous", priority="critical", members=[Target(id="AB12CDE")])]
    )
    result: Sighting = tracker.find("AB12CDE")
    assert result.target.group == "dangerous"
    assert result.target.description == "dangerous"


def test_classify_target_known_no_description(tracker: Tracker) -> None:
    tracker.target_config = TargetSettings(groups=[TargetGroup(name="known", members=[Target(id="AB12CDE")])])
    result = tracker.find("AB12CDE")
    assert result.target.group == "known"
    assert result.target.description == "known"


def test_fuzzy_match_known_within_tolerance(tracker: Tracker) -> None:
    # "AB12CDF" is distance 1 from "AB12CDE"
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="known", members=[Target(id="AB12CDE", description="Alice")])],
        auto_match_tolerance=1,
    )

    result = tracker.find("AB12CDF")
    assert result.target.group == "known"
    assert result.target.description == "Alice"
    assert result.target.priority == "medium"


def test_fuzzy_match_known_beyond_tolerance(tracker: Tracker) -> None:
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="known", members=[Target(id="AB12CDE", description="Alice")])],
        auto_match_tolerance=1,
    )

    result = tracker.find("AB12CXX")
    assert result.target.group is None
    assert result.target.priority == "high"


def test_fuzzy_match_known_disabled(tracker: Tracker) -> None:
    # tolerance=0 means only exact matches; "AB12CDF" must not match "AB12CDE"
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="known", members=[Target(id="AB12CDE", description="Alice")])],
        auto_match_tolerance=0,
    )

    result: Sighting = tracker.find("AB12CDF")
    assert result.target.group is None


def test_fuzzy_match_dangerous_within_tolerance(tracker: Tracker) -> None:
    # "PK12TSX" is distance 1 from "PK12TST"
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="dangerous", priority="critical", members=[Target(id="PK12TST", description="Suspect")])],
        auto_match_tolerance=1,
    )

    result = tracker.find("PK12TSX")
    assert result.target.group == "dangerous"
    assert result.target.description == "Suspect"
    assert result.target.priority == "critical"


def test_fuzzy_match_dangerous_beyond_tolerance(tracker: Tracker) -> None:
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="dangerous", priority="critical", members=[Target(id="PK12TST", description="Suspect")])],
        auto_match_tolerance=3,
    )

    result = tracker.find("PK12XXX")
    assert result.target.group == "dangerous"
    assert result.target.description == "Suspect"

    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="dangerous", priority="critical", members=[Target(id="PK12TST", description="Suspect")])],
        auto_match_tolerance=2,
    )
    result = tracker.find("PK12XXX")
    assert result.target.group is None


def test_fuzzy_match_picks_closest_known(tracker: Tracker) -> None:
    # "AB12CDF" is distance 1 from "AB12CDE" and distance 2 from "AB12CDZ"
    tracker.target_config = TargetSettings(
        groups=[
            TargetGroup(
                name="known",
                members=[
                    Target(id="AB12CDE", description="Alice"),
                    Target(id="AB12CDZ", description="Bob"),
                ],
            )
        ],
        auto_match_tolerance=2,
    )

    result = tracker.find("AB12CDF")
    assert result.target.group == "known"
    assert result.target.description == "Alice"


def test_fuzzy_match_exact_preferred(tracker: Tracker) -> None:
    # Exact match should win even when tolerance > 0
    tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="known", members=[Target(id="AB12CDE", description="Exact match")])],
        auto_match_tolerance=2,
    )

    result: Sighting = tracker.find("AB12CDE")
    assert result.target.group == "known"
    assert result.target.description == "Exact match"


def test_fuzzy_match_both_known_and_dangerous(tracker: Tracker) -> None:
    # "AB12CDF" is distance 1 from dangerous "AB12CDX" but distance 4 from known "AB12ZZZ"
    tracker.target_config = TargetSettings(
        groups=[
            TargetGroup(name="known", members=[Target(id="AB12ZZZ", description="Alice")]),
            TargetGroup(name="dangerous", priority="critical", members=[Target(id="AB12CDX", description="Threat")]),
        ],
        auto_match_tolerance=1,
    )

    result: Sighting = tracker.find("AB12CDF")
    assert result.target.group == "dangerous"
