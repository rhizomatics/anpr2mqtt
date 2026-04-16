from typing import Any

from anpr2mqtt.settings import Target, TargetGroup, TargetSettings


def _group(**kwargs: Any) -> TargetGroup:
    return TargetGroup(
        name="known",
        priority="medium",
        icon="mdi:car",
        entity_id="sensor.known",
        members=[Target(id="ABC123")],
        **kwargs,
    )


def _member(group: TargetGroup) -> Target:
    return group.members[0]


# ── inheritance (None fields pick up group values) ───────────────────────────


def test_inherits_priority() -> None:
    assert _member(_group()).priority == "medium"


def test_inherits_icon() -> None:
    ts = TargetSettings(groups=[_group()])
    assert ts.groups[0].members[0].icon == "mdi:car"


def test_inherits_entity_id() -> None:
    assert _member(_group()).entity_id == "sensor.known"


def test_inherits_description_from_group_name() -> None:
    assert _member(_group()).description == "known"


# ── no override (set fields are preserved) ───────────────────────────────────


def test_does_not_override_priority() -> None:
    g = TargetGroup(name="known", priority="medium", members=[Target(id="ABC123", priority="critical")])
    assert g.members[0].priority == "critical"


def test_does_not_override_icon() -> None:
    g = TargetGroup(name="known", icon="mdi:car", members=[Target(id="ABC123", icon="mdi:truck")])
    assert g.members[0].icon == "mdi:truck"


def test_does_not_override_entity_id() -> None:
    g = TargetGroup(name="known", entity_id="sensor.group", members=[Target(id="ABC123", entity_id="sensor.mine")])
    assert g.members[0].entity_id == "sensor.mine"


def test_does_not_override_description() -> None:
    g = TargetGroup(name="known", members=[Target(id="ABC123", description="My car")])
    assert g.members[0].description == "My car"


# ── TargetSettings.icon propagation ─────────────────────────────────────────


def test_settings_icon_propagates_to_group() -> None:
    ts = TargetSettings(icon="mdi:bus", groups=[TargetGroup(name="known", members=[Target(id="ABC123")])])
    assert ts.groups[0].icon == "mdi:bus"


def test_settings_icon_propagates_to_member() -> None:
    ts = TargetSettings(icon="mdi:bus", groups=[TargetGroup(name="known", members=[Target(id="ABC123")])])
    assert ts.groups[0].members[0].icon == "mdi:bus"


def test_settings_icon_does_not_override_group_icon() -> None:
    ts = TargetSettings(icon="mdi:bus", groups=[TargetGroup(name="known", icon="mdi:car", members=[Target(id="ABC123")])])
    assert ts.groups[0].icon == "mdi:car"


def test_settings_icon_does_not_override_member_icon() -> None:
    ts = TargetSettings(
        icon="mdi:bus",
        groups=[TargetGroup(name="known", members=[Target(id="ABC123", icon="mdi:truck")])],
    )
    assert ts.groups[0].members[0].icon == "mdi:truck"


def test_settings_icon_none_leaves_group_icon_none() -> None:
    ts = TargetSettings(groups=[TargetGroup(name="known", members=[Target(id="ABC123")])])
    assert ts.groups[0].icon is None
    assert ts.groups[0].members[0].icon is None
