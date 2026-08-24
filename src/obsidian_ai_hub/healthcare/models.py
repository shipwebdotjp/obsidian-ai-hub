"""Dataclass definitions for healthcare domain (Apple Health export)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HealthRecord:
    import_id: str
    type: str
    value_text: str | None
    value_numeric: float | None
    unit: str | None
    source_name: str
    source_version: str | None
    device_raw: str | None
    creation_date: str | None
    start_date: str
    end_date: str
    fingerprint: str
    metadata: tuple[tuple[str, str], ...] = field(
        default_factory=tuple, compare=False, hash=False
    )


@dataclass(frozen=True)
class HealthWorkout:
    import_id: str
    activity_type: str
    duration: float | None
    duration_unit: str | None
    total_distance: float | None
    total_distance_unit: str | None
    total_energy_burned: float | None
    total_energy_burned_unit: str | None
    source_name: str
    source_version: str | None
    device_raw: str | None
    creation_date: str | None
    start_date: str
    end_date: str
    fingerprint: str
    # Workout metadata is stored in health_workout_metadata; kept symmetrical
    # with HealthRecord.metadata but optional for import symmetry.
    metadata: tuple[tuple[str, str], ...] = field(
        default_factory=tuple, compare=False, hash=False
    )
