"""Tests for recurring events service and media protection."""

import pytest
from datetime import date
from obsidian_ai_hub.web.services import recurring_events as re_service
from obsidian_ai_hub.media import store as media_store
from obsidian_ai_hub.media.generation import GeneratedImage


def test_event_type_crud():
    # Create
    et = re_service.create_event_type(
        name="脱毛",
        properties=[
            {
                "key": "part",
                "display_name": "部位",
                "data_type": "select",
                "options": [
                    {"option_key": "beard", "display_name": "ひげ"},
                    {"option_key": "arm", "display_name": "腕"},
                ],
            }
        ],
    )
    assert et["name"] == "脱毛"
    assert len(et["properties"]) == 1
    assert et["properties"][0]["key"] == "part"
    assert len(et["properties"][0]["options"]) == 2

    # Get
    et_fetched = re_service.get_event_type(et["type_id"])
    assert et_fetched["type_id"] == et["type_id"]

    # Update name
    et_updated = re_service.update_event_type(et["type_id"], name="脱毛（医療）")
    assert et_updated["name"] == "脱毛（医療）"

    # Delete
    re_service.delete_event_type(et["type_id"])
    with pytest.raises(re_service.EventTypeNotFoundError):
        re_service.get_event_type(et["type_id"])


def test_series_creation_and_locking():
    # Create Event Type
    et = re_service.create_event_type(
        name="オイル交換",
        properties=[
            {
                "key": "car",
                "display_name": "車種",
                "data_type": "text",
            }
        ],
    )

    # Create Series with start record
    today_str = re_service.get_jst_today().isoformat()
    series = re_service.create_series_with_start_record(
        type_id=et["type_id"],
        interval_value=6,
        interval_unit="month",
        property_values={"car": "RAV4"},
        executed_on=today_str,
        note="初回記録",
        count_contribution=1,
    )
    assert series["type_name"] == "オイル交換"
    assert series["interval_value"] == 6
    assert series["interval_unit"] == "month"
    assert series["properties_dict"] == {"car": "RAV4"}
    assert series["total_count"] == 1
    assert len(series["records"]) == 1
    assert series["records"][0]["is_start_record"] is True

    # Duplicate series creation should raise SeriesAlreadyExistsError
    with pytest.raises(re_service.SeriesAlreadyExistsError):
        re_service.create_series_with_start_record(
            type_id=et["type_id"],
            interval_value=3,
            interval_unit="month",
            property_values={"car": "RAV4"},
            executed_on=today_str,
        )

    # Now schema modifications that break structure should be locked
    with pytest.raises(re_service.EventTypeSchemaLockedError):
        re_service.update_event_type(
            et["type_id"],
            properties=[
                {"key": "car", "display_name": "車種", "data_type": "text"},
                {"key": "mileage", "display_name": "走行距離", "data_type": "number"},
            ],
        )

    # Deleting event type with existing series should fail
    with pytest.raises(re_service.EventTypeSchemaLockedError):
        re_service.delete_event_type(et["type_id"])


def test_execution_records_and_cascade_deletion(tmp_path, monkeypatch):
    monkeypatch.setattr("obsidian_ai_hub.utils.config.IMAGE_GENERATION_OUTPUT_DIR", str(tmp_path))

    # Save a media item
    img = GeneratedImage(data=b"fake-image-bytes", mime_type="image/png", output_format="png")
    media_ref = media_store.save_generated_image(
        img, prompt="test photo", model="dall-e-3", source="upload"
    )
    media_id = media_ref["media_id"]

    # Create Event Type
    et = re_service.create_event_type(name="散髪")

    today = re_service.get_jst_today()
    exec1 = today.isoformat()

    # Create Series
    series = re_service.create_series_with_start_record(
        type_id=et["type_id"],
        interval_value=1,
        interval_unit="month",
        property_values={},
        executed_on=exec1,
        note="カット＋シャンプー",
        media_id=media_id,
        count_contribution=5,
    )
    assert series["total_count"] == 5

    # Media deletion should be rejected because it is referenced
    with pytest.raises(media_store.MediaReferencedError):
        media_store.delete_media(media_id)

    # Add a second record
    series = re_service.add_execution_record(
        series_id=series["series_id"],
        executed_on=today.isoformat(),
        note="2回目の記録",
    )
    assert series["total_count"] == 6  # 5 + 1
    assert len(series["records"]) == 2

    # Delete non-start record
    record_ids = [r["record_id"] for r in series["records"] if not r["is_start_record"]]
    s_id, is_deleted = re_service.delete_execution_record(record_ids[0])
    assert is_deleted is False
    assert s_id == series["series_id"]

    # Delete start record (the last remaining record)
    start_rec_id = [r["record_id"] for r in series["records"] if r["is_start_record"]][0]
    s_id, is_deleted = re_service.delete_execution_record(start_rec_id)
    assert is_deleted is True
    assert s_id is None

    # Series should now be gone
    with pytest.raises(re_service.SeriesNotFoundError):
        re_service.get_series_detail(series["series_id"])

    # Now media deletion should succeed since reference is cleared (cascade deleted series)
    assert media_store.delete_media(media_id) is True


def test_month_end_rounding():
    d = date(2024, 1, 31)
    res = re_service.compute_next_due_date(d, 1, "month")
    assert res == date(2024, 2, 29)  # 2024 is leap year

    d2 = date(2023, 1, 31)
    res2 = re_service.compute_next_due_date(d2, 1, "month")
    assert res2 == date(2023, 2, 28)  # 2023 non leap year
