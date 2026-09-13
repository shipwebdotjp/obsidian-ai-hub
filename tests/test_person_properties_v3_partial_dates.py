import pytest
import sqlite3
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils.dates import (
    get_partial_date_bounds,
    parse_and_normalize_partial_date,
)
from obsidian_ai_hub.utils.periods import temporal_ranges_overlap
from obsidian_ai_hub.web.services import person_properties as prop_service
from obsidian_ai_hub.web.services.person_properties import InvalidValueError, SingleCardinalityOverlapError


def test_parse_and_normalize_partial_date():
    # YYYY
    assert parse_and_normalize_partial_date("1990") == "1990"
    # YYYY-MM
    assert parse_and_normalize_partial_date("1990-05") == "1990-05"
    assert parse_and_normalize_partial_date("1990/5") == "1990-05"
    # YYYY-MM-DD
    assert parse_and_normalize_partial_date("1990-05-15") == "1990-05-15"
    assert parse_and_normalize_partial_date("1990/5/3") == "1990-05-03"

    # Invalid dates
    with pytest.raises(ValueError):
        parse_and_normalize_partial_date("1990-13")
    with pytest.raises(ValueError):
        parse_and_normalize_partial_date("1990-02-30")
    with pytest.raises(ValueError):
        parse_and_normalize_partial_date("invalid")


def test_get_partial_date_bounds():
    assert get_partial_date_bounds("1990") == ("1990-01-01", "1990-12-31")
    assert get_partial_date_bounds("1990-05") == ("1990-05-01", "1990-05-31")
    assert get_partial_date_bounds("1990-05-15") == ("1990-05-15", "1990-05-15")
    # Leap year Feb
    assert get_partial_date_bounds("2024-02") == ("2024-02-01", "2024-02-29")
    # Non-leap year Feb
    assert get_partial_date_bounds("2025-02") == ("2025-02-01", "2025-02-28")


def test_validity_period_inversion():
    # valid_from_min <= valid_until_max: valid
    # 2025-05 (2025-05-01..2025-05-31) vs 2025-05-10 (2025-05-10..2025-05-10) -> 2025-05-01 <= 2025-05-10: True
    norm_from = parse_and_normalize_partial_date("2025-05")
    norm_until = parse_and_normalize_partial_date("2025-05-10")
    f_min, _ = get_partial_date_bounds(norm_from)
    _, u_max = get_partial_date_bounds(norm_until)
    assert f_min <= u_max

    # 2025-06 (2025-06-01..2025-06-30) vs 2025-05 (2025-05-01..2025-05-31) -> 2025-06-01 <= 2025-05-31: False -> inverted
    norm_from = parse_and_normalize_partial_date("2025-06")
    norm_until = parse_and_normalize_partial_date("2025-05")
    f_min, _ = get_partial_date_bounds(norm_from)
    _, u_max = get_partial_date_bounds(norm_until)
    assert f_min > u_max


def test_crud_and_single_cardinality_with_partial_dates(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_MEMORY_SQLITE_PATH", str(tmp_path / "test.db"))
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('p1', 'p1', 'Person 1')"
    )
    conn.commit()
    conn.close()

    defn = prop_service.create_property_definition(
        key="birth_date",
        display_name="生年月日",
        data_type="date",
        cardinality="single",
        source_type="database",
    )
    def_id = defn["property_definition_id"]

    # 1. Create with YYYY-MM
    val1 = prop_service.create_person_property_value(
        person_id="p1",
        property_definition_id=def_id,
        value="1990-05",
        valid_from="1990",
        valid_until="2025-05",
    )
    assert val1["value_date"] == "1990-05"
    assert val1["value"] == "1990-05"
    assert val1["valid_from"] == "1990"
    assert val1["valid_until"] == "2025-05"

    # 2. Overlapping single-cardinality property with different value -> SingleCardinalityOverlapError
    with pytest.raises(SingleCardinalityOverlapError):
        prop_service.create_person_property_value(
            person_id="p1",
            property_definition_id=def_id,
            value="1991-01",
            valid_from="2020",
            valid_until="2030",
        )

    # 3. Create non-overlapping single-cardinality value
    val2 = prop_service.create_person_property_value(
        person_id="p1",
        property_definition_id=def_id,
        value="2030-01-01",
        valid_from="2026",
        valid_until="2040",
    )
    assert val2["value_date"] == "2030-01-01"

    # 4. Inverted valid_from > valid_until -> InvalidValueError
    with pytest.raises(InvalidValueError):
        prop_service.create_person_property_value(
            person_id="p1",
            property_definition_id=def_id,
            value="2050",
            valid_from="2050-06",
            valid_until="2050-05",
        )


def test_temporal_ranges_overlap_primitive():
    # Overlapping partial dates: 1990-05 (1990-05-01..1990-05-31) and 1990 (1990-01-01..1990-12-31)
    min1, max1 = get_partial_date_bounds("1990-05")
    min2, max2 = get_partial_date_bounds("1990")
    assert temporal_ranges_overlap(min1, max1, min2, max2)

    # Non-overlapping: 1990-05 and 1990-06
    min3, max3 = get_partial_date_bounds("1990-06")
    assert not temporal_ranges_overlap(min1, max1, min3, max3)

    # Search primitive helper
    assert prop_service.matches_temporal_condition(
        val_date_min=min1,
        val_date_max=max1,
        valid_from_min="1980-01-01",
        valid_until_max="2000-12-31",
        query_start="1990-01",
        query_end="1990-12",
    )


def test_ai_properties_projection_partial_dates(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_MEMORY_SQLITE_PATH", str(tmp_path / "test.db"))
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('p2', 'p2', 'Person 2')"
    )
    conn.commit()
    conn.close()

    defn = prop_service.create_property_definition(
        key="graduation_date",
        display_name="卒業年月",
        data_type="date",
        cardinality="single",
        source_type="database",
    )
    def_id = defn["property_definition_id"]

    prop_service.create_person_property_value(
        person_id="p2",
        property_definition_id=def_id,
        value="2012-03",
        valid_from="2008-04",
        valid_until="2012-03",
    )

    ai_props = prop_service.get_person_properties_for_ai("p2")
    assert len(ai_props) == 1
    assert ai_props[0]["key"] == "graduation_date"
    assert ai_props[0]["value"] == "2012-03"
    assert ai_props[0]["valid_from"] == "2008-04"
    assert ai_props[0]["valid_until"] == "2012-03"
