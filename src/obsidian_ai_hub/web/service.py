"""Public service facade for the web layer.

Re-exports all service functions from the feature subpackage to preserve the
``service.*`` import surface used by ``api.py``, tests, and
``summary/project_utils.py``. No logic lives here.
"""

from obsidian_ai_hub.web.services.dashboard import (
    find_selectable_years,
    get_dashboard_browse,
    get_dashboard_day_details,
    get_dashboard_home,
    get_dashboard_stats,
    get_day_activity_times,
    parse_iso_datetime,
)
from obsidian_ai_hub.web.services.execution_logs import (
    get_command_run_detail,
    get_llm_call_detail,
    list_execution_logs,
)
from obsidian_ai_hub.web.services.hitl import (
    cancel_hitl_run,
    get_hitl_run_detail,
    list_hitl_runs,
    resolve_display_title,
    submit_hitl_answer,
)
from obsidian_ai_hub.web.services.memory import (
    REVIEW_ACTIONS,
    batch_delete,
    batch_review,
    delete_memory,
    get_events,
    get_memory,
    get_memory_options,
    list_memories,
    render_copilot_profile,
    resolve_memory,
    review_memory,
    update_memory,
)
from obsidian_ai_hub.web.services.people import (
    AliasConflictError,
    AssignmentConflictError,
    MainNameConflictError,
    VaultLinkedPersonError,
    delete_person,
    delete_person_alias,
    get_person_detail,
    list_people,
    update_unlinked_person,
)
from obsidian_ai_hub.web.services.people_candidates import (
    assign_candidate_summary,
    get_person_candidate_detail,
    list_person_candidates,
    promote_person_candidate,
    resolve_person_candidate,
)
from obsidian_ai_hub.web.services.people_merge import (
    consolidate_summary_links,
    get_duplicate_candidates,
    merge_people,
    preview_people_merge,
    verify_people_merge,
)
from obsidian_ai_hub.web.services.people_sync import (
    get_vault_report_dynamic,
    sync_people,
)
from obsidian_ai_hub.web.services.projects import (
    ProjectConflictError,
    create_project,
    deserialize_candidate,
    deserialize_project,
    get_project_candidate_detail,
    get_project_detail,
    list_project_candidates,
    list_projects,
    resolve_project_candidate,
    update_project,
)
from obsidian_ai_hub.web.services.research import (
    get_research_theme,
    list_research_themes,
    rerun_research_theme,
    run_research_theme,
)
from obsidian_ai_hub.web.services.summary import (
    delete_summary_detail,
    get_edit_options,
    update_summary_detail,
)
from obsidian_ai_hub.web.services.task_config import (
    TaskConfigConflictError,
    get_task_config,
    preview_command,
    update_task_config,
)
from obsidian_ai_hub.web.services.vault import (
    get_vault_file,
    search_vault,
)
