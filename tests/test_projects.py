import json
import pytest
from datetime import datetime
from unittest import mock
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.web import service, schemas


@pytest.fixture(autouse=True)
def mock_people_notes(monkeypatch):
    monkeypatch.setattr(
        "obsidian_ai_hub.utils.people_loader.load_and_validate_people_notes",
        lambda: {},
    )


def test_project_and_candidate_creation_and_rejection(test_memory_db_path):
    # 1. Create a dummy summary that extracts project candidates
    record = {
        "period_type": "day",
        "period_key": "2026-07-25",
        "period_start": "2026-07-25",
        "period_end": "2026-07-25",
        "summary": "Worked on a new side-project named Project X and personal blog",
        "project_candidates": [
            {
                "name": "Project X",
                "domain": "work",
                "goal": "Build an AI tool",
                "description": "Side project description",
                "keywords": ["AI", "tool"],
                "start_date": "2026-07-25",
                "evidence": "Mentioned working on Project X in log"
            },
            {
                "name": "Personal Blog",
                "domain": "personal",
                "goal": "Write thoughts",
                "description": "Personal blog description",
                "keywords": ["blog", "personal"],
                "evidence": "Mentioned personal blog"
            }
        ]
    }
    summary_store.upsert_summary(record)

    # Retrieve and verify candidate was saved
    candidates = service.list_project_candidates(status="unresolved")
    assert len(candidates) == 2
    cand_x = [c for c in candidates if c["display_name"] == "Project X"][0]
    assert cand_x["domain"] == "work"
    assert cand_x["status"] == "unresolved"
    assert cand_x["keywords"] == ["AI", "tool"]
    assert cand_x["evidence"] == "Mentioned working on Project X in log"

    cand_blog = [c for c in candidates if c["display_name"] == "Personal Blog"][0]
    assert cand_blog["domain"] == "personal"

    # 2. Reject candidate Personal Blog
    resolve_req = schemas.ProjectCandidateResolveRequest(action="reject")
    service.resolve_project_candidate(cand_blog["candidate_id"], resolve_req)

    # Verify candidate is rejected
    rejected_candidates = service.list_project_candidates(status="rejected")
    assert len(rejected_candidates) == 1
    assert rejected_candidates[0]["display_name"] == "Personal Blog"

    unresolved_candidates = service.list_project_candidates(status="unresolved")
    assert len(unresolved_candidates) == 1
    assert unresolved_candidates[0]["display_name"] == "Project X"

    # 3. Re-ingest Daily Summary containing Personal Blog: should be filtered out / ignored
    record_re = {
        "period_type": "day",
        "period_key": "2026-07-25",
        "period_start": "2026-07-25",
        "period_end": "2026-07-25",
        "summary": "Worked on blog",
        "project_candidates": [
            {
                "name": "Personal Blog",
                "domain": "personal",
                "evidence": "Blog again"
            }
        ]
    }
    summary_store.upsert_summary(record_re)

    # Since it is rejected, summary_project_candidates should NOT link Personal Blog
    got = summary_store.get_summary_by_period("day", "2026-07-25")
    assert len(got["project_candidates"]) == 0

    # 4. Reopen rejected Personal Blog
    reopen_req = schemas.ProjectCandidateResolveRequest(action="reopen_rejected")
    service.resolve_project_candidate(cand_blog["candidate_id"], reopen_req)

    # Verify it is unresolved again
    assert len(service.list_project_candidates(status="unresolved")) == 2


def test_approve_new_and_link_existing_project(test_memory_db_path):
    # Create summaries linked to candidate Project X
    record1 = {
        "period_type": "day",
        "period_key": "2026-07-26",
        "summary": "Day 1 working on Project X",
        "project_candidates": [{"name": "Project X", "domain": "work", "evidence": "X evidence"}]
    }
    summary_store.upsert_summary(record1)

    record2 = {
        "period_type": "day",
        "period_key": "2026-07-27",
        "summary": "Day 2 working on Project X",
        "project_candidates": [{"name": "Project X", "domain": "work", "evidence": "X evidence 2"}]
    }
    summary_store.upsert_summary(record2)

    candidates = service.list_project_candidates(status="unresolved")
    assert len(candidates) == 1
    cand_id = candidates[0]["candidate_id"]

    # Approve candidate as a new official project
    resolve_req = schemas.ProjectCandidateResolveRequest(
        action="approve_new",
        display_name="Official Project X",
        domain="work",
        status="active",
        goal="Conquer the market",
        keywords=["official", "x"]
    )
    service.resolve_project_candidate(cand_id, resolve_req)

    # Verify candidate state is updated
    c_detail = service.get_project_candidate_detail(cand_id)
    assert c_detail["status"] == "resolved"

    # Verify official project is created
    projs = service.list_projects()
    assert len(projs) == 1
    proj = projs[0]
    assert proj["display_name"] == "Official Project X"
    assert proj["domain"] == "work"
    assert proj["status"] == "active"
    assert proj["keywords"] == ["official", "x"]

    # Verify summaries automatically migrated to the new official project
    p_detail = service.get_project_detail(proj["project_id"])
    assert len(p_detail["summaries"]) == 2
    keys = {s["period_key"] for s in p_detail["summaries"]}
    assert keys == {"2026-07-26", "2026-07-27"}

    # Original candidate links are removed from summaries
    got1 = summary_store.get_summary_by_period("day", "2026-07-26")
    assert len(got1["project_candidates"]) == 0
    assert got1["projects"] == ["Official Project X"]

    got2 = summary_store.get_summary_by_period("day", "2026-07-27")
    assert len(got2["project_candidates"]) == 0
    assert got2["projects"] == ["Official Project X"]

    # Now, let's create another candidate "Project Y"
    record3 = {
        "period_type": "day",
        "period_key": "2026-07-28",
        "summary": "Working on Project Y",
        "project_candidates": [{"name": "Project Y", "domain": "personal", "evidence": "Y evidence"}]
    }
    summary_store.upsert_summary(record3)

    candidates_y = service.list_project_candidates(status="unresolved")
    assert len(candidates_y) == 1
    cand_y_id = candidates_y[0]["candidate_id"]

    # Link candidate Project Y to the existing project (Official Project X)
    link_req = schemas.ProjectCandidateResolveRequest(
        action="link_existing",
        target_project_id=proj["project_id"]
    )
    service.resolve_project_candidate(cand_y_id, link_req)

    # Verify candidate Project Y is resolved
    c_y_detail = service.get_project_candidate_detail(cand_y_id)
    assert c_y_detail["status"] == "resolved"

    # Verify summary for Project Y is migrated to Official Project X
    got3 = summary_store.get_summary_by_period("day", "2026-07-28")
    assert len(got3["project_candidates"]) == 0
    assert got3["projects"] == ["Official Project X"]

    # Try linking to a non-existent project_id to verify error handling
    link_err_req = schemas.ProjectCandidateResolveRequest(
        action="link_existing",
        target_project_id=99999
    )
    with pytest.raises(ValueError, match="Target project not found"):
        service.resolve_project_candidate(cand_y_id, link_err_req)


def test_recreation_and_manual_create_update_projects(test_memory_db_path):
    # Create Project manually
    create_req = schemas.ProjectCreateRequest(
        display_name="Manual Proj",
        domain="personal",
        status="inquiry",
        goal="Write a book",
        keywords=["book", "novel"]
    )
    proj = service.create_project(create_req)
    assert proj["project_id"] is not None
    assert proj["display_name"] == "Manual Proj"
    assert proj["domain"] == "personal"
    assert proj["status"] == "inquiry"

    # Update Project
    update_req = schemas.ProjectUpdateRequest(
        display_name="Updated Proj Name",
        status="active",
        goal="Publish a bestseller"
    )
    updated = service.update_project(proj["project_id"], update_req)
    assert updated["display_name"] == "Updated Proj Name"
    assert updated["status"] == "active"
    assert updated["goal"] == "Publish a bestseller"

    # Test listing with filters
    work_projs = service.list_projects(domain="work")
    assert len(work_projs) == 0

    personal_projs = service.list_projects(domain="personal")
    assert len(personal_projs) == 1
    assert personal_projs[0]["display_name"] == "Updated Proj Name"

    # Test name collision
    create_col = schemas.ProjectCreateRequest(display_name="updated proj name")
    with pytest.raises(service.ProjectConflictError):
        service.create_project(create_col)


def test_weekly_and_monthly_project_inheritance(test_memory_db_path):
    # Create an official project
    create_req = schemas.ProjectCreateRequest(display_name="Inherited Proj", domain="work", status="active")
    proj = service.create_project(create_req)
    proj_id = proj["project_id"]

    # Save daily summaries
    # Day 1: Links to official project and has candidate A
    summary_store.upsert_summary({
        "period_type": "day",
        "period_key": "2026-07-20",
        "summary": "Day 1 info",
        "project_ids": [proj_id],
        "project_candidates": [{"name": "Candidate A", "domain": "personal", "evidence": "A evidence"}]
    })

    # Day 2: Has candidate B
    summary_store.upsert_summary({
        "period_type": "day",
        "period_key": "2026-07-21",
        "summary": "Day 2 info",
        "project_candidates": [{"name": "Candidate B", "domain": "work", "evidence": "B evidence"}]
    })

    # Day 3: Empty project links
    summary_store.upsert_summary({
        "period_type": "day",
        "period_key": "2026-07-22",
        "summary": "Day 3 info",
    })

    # Trigger weekly summarization for 2026-07-20 (falls in week W30)
    from obsidian_ai_hub import summerize_week
    # Mock LLM response for week summary
    with mock.patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", return_value='{"summary": "Mocked week description", "keywords": [], "topics": []}'):
        summerize_week.summarize_week("2026-07-20")

    # Load weekly summary and verify project/candidate inheritance
    dt = datetime.strptime("2026-07-20", "%Y-%m-%d")
    iso_year, iso_week, _ = dt.isocalendar()
    week_key = f"{iso_year}-W{iso_week:02d}"

    week_sum = summary_store.get_summary_by_period("week", week_key)
    assert week_sum is not None
    assert week_sum["projects"] == ["Inherited Proj"]
    assert week_sum["project_ids"] == [proj_id]

    cand_names = {c["display_name"] for c in week_sum["project_candidates"]}
    assert cand_names == {"Candidate A", "Candidate B"}

    # Now trigger monthly summarization for 2026-07-01
    from obsidian_ai_hub import summerize_month
    with mock.patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", return_value='{"summary": "Mocked month description", "keywords": [], "topics": []}'):
        summerize_month.summarize_month(dt)

    month_sum = summary_store.get_summary_by_period("month", "2026-07")
    assert month_sum is not None
    assert month_sum["projects"] == ["Inherited Proj"]
    assert month_sum["project_ids"] == [proj_id]

    month_cand_names = {c["display_name"] for c in month_sum["project_candidates"]}
    assert month_cand_names == {"Candidate A", "Candidate B"}


def test_project_utils_helpers(test_memory_db_path):
    from obsidian_ai_hub.summary.project_utils import get_active_projects_for_prompt, inherit_projects_and_candidates

    # Check that get_active_projects_for_prompt retrieves active, inquiry, paused projects
    # Let's create one of each status
    service.create_project(schemas.ProjectCreateRequest(display_name="Proj Inquiry", domain="work", status="inquiry"))
    service.create_project(schemas.ProjectCreateRequest(display_name="Proj Active", domain="work", status="active"))
    service.create_project(schemas.ProjectCreateRequest(display_name="Proj Paused", domain="personal", status="paused"))
    service.create_project(schemas.ProjectCreateRequest(display_name="Proj Completed", domain="personal", status="completed"))

    active_prompt_projs = get_active_projects_for_prompt()
    # Should get 3 projects (Inquiry, Active, Paused), but not Completed
    assert len(active_prompt_projs) == 3
    names = {p["display_name"] for p in active_prompt_projs}
    assert "Proj Inquiry" in names
    assert "Proj Active" in names
    assert "Proj Paused" in names
    assert "Proj Completed" not in names

    # Test inherit_projects_and_candidates
    sub_records = [
        {
            "project_ids": [123],
            "project_candidates": [{"name": "Cand Helper 1", "domain": "personal"}]
        },
        None,
        {
            "project_ids": [456],
            "project_candidates": [{"name": "Cand Helper 1", "domain": "personal"}, {"name": "Cand Helper 2", "domain": "work"}]
        }
    ]
    p_ids, p_candidates = inherit_projects_and_candidates(sub_records)
    assert set(p_ids) == {123, 456}
    assert len(p_candidates) == 2
    cand_names = {c["display_name"] for c in p_candidates}
    assert cand_names == {"Cand Helper 1", "Cand Helper 2"}


def test_weekly_project_notes_inheritance_and_summarization(test_memory_db_path):
    create_req = schemas.ProjectCreateRequest(display_name="Inherited Proj", domain="work", status="active")
    proj = service.create_project(create_req)
    proj_id = proj["project_id"]

    summary_store.upsert_summary({
        "period_type": "day",
        "period_key": "2026-07-20",
        "summary": "Day 1",
        "project_notes": [{"project_id": proj_id, "note": "Refactored auth"}],
    })

    summary_store.upsert_summary({
        "period_type": "day",
        "period_key": "2026-07-21",
        "summary": "Day 2",
    })

    from obsidian_ai_hub import summerize_week
    with mock.patch(
        "obsidian_ai_hub.utils.llm_client.generate_llm_response",
        return_value=json.dumps({
            "summary": "Week summary",
            "keywords": [],
            "topics": [],
            "project_notes": [
                {"project_id": proj_id, "note": "Made progress on refactoring"},
                {"project_id": 999, "note": "Should be ignored"},
            ],
        }),
    ):
        summerize_week.summarize_week("2026-07-20")

    dt = datetime.strptime("2026-07-20", "%Y-%m-%d")
    iso_year, iso_week, _ = dt.isocalendar()
    week_key = f"{iso_year}-W{iso_week:02d}"

    week_sum = summary_store.get_summary_by_period("week", week_key)
    assert week_sum is not None
    # Inherited project ID is present
    assert proj_id in week_sum["project_ids"]
    # LLM note for inherited project preserved, invalid ID 999 ignored
    pn_list = week_sum["project_notes"]
    assert len(pn_list) == 1
    assert pn_list[0]["project_id"] == proj_id
    assert pn_list[0]["note"] == "Made progress on refactoring"


def test_project_detail_includes_notes(test_memory_db_path):
    proj = service.create_project(schemas.ProjectCreateRequest(display_name="Test Proj", domain="work"))

    summary_store.upsert_summary({
        "period_type": "day",
        "period_key": "2026-07-28",
        "summary": "Day with note",
        "project_notes": [{"project_id": proj["project_id"], "note": "Project activity memo"}],
    })

    detail = service.get_project_detail(proj["project_id"])
    assert detail is not None
    assert len(detail["summaries"]) == 1
    summary = detail["summaries"][0]
    assert summary["period_key"] == "2026-07-28"
    assert summary.get("note") == "Project activity memo"
