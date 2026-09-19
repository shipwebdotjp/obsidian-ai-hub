"""Per-purpose policies for long-term memory compilation.

Callers pass a stable purpose string (e.g. ``"make-target"``,
``"summarize-day"``). The purpose decides which memory kinds may be injected,
how many tokens may be spent, how the reference block is formatted, and whether
person-scoped memories may be included.

Operators can override any built-in policy from ``config/config.yml``::

    memory:
      purposes:
        summarize-day:
          kinds: [preference, decision_policy]
          budget: 400
          format: evidence
          include_person: true

Unknown purposes fall back to the permissive default (all kinds, the global
``memory.context_max_tokens`` budget, evidence format, user scope only), which
keeps ``--memory-compile --for <anything>`` backward compatible.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from obsidian_ai_hub.utils import config

ALL_MEMORY_KINDS = frozenset(
    {
        "preference",
        "decision_policy",
        "fact",
        "commitment",
        "pattern",
        "episode",
    }
)

FORMAT_EVIDENCE = "evidence"
FORMAT_FENCED = "fenced"
ALLOWED_FORMATS = frozenset({FORMAT_EVIDENCE, FORMAT_FENCED})


@dataclass(frozen=True)
class PurposePolicy:
    """Resolved policy for one purpose.

    ``kinds`` is ``None`` for "all kinds". ``budget`` is ``None`` to inherit the
    global ``memory.context_max_tokens`` value. ``person_kinds`` filters the
    person-scope section independently; when ``None`` the person section reuses
    ``kinds``. ``person_budget`` caps the person section independently; when
    ``None`` the person section uses whatever budget remains after the user
    section.
    """

    kinds: frozenset[str] | None
    budget: int | None
    format: str
    include_person: bool = False
    person_kinds: frozenset[str] | None = None
    person_budget: int | None = None

    @property
    def resolved_kinds(self) -> frozenset[str]:
        return self.kinds if self.kinds is not None else ALL_MEMORY_KINDS

    @property
    def resolved_person_kinds(self) -> frozenset[str]:
        if self.person_kinds is not None:
            return self.person_kinds
        return self.resolved_kinds


_DEFAULT_POLICY = PurposePolicy(
    kinds=None,
    budget=None,
    format=FORMAT_EVIDENCE,
    include_person=False,
)

_BUILTIN_POLICIES: dict[str, PurposePolicy] = {
    "make-target": _DEFAULT_POLICY,
    "planner": _DEFAULT_POLICY,
    "summarize-day": PurposePolicy(
        kinds=frozenset({"preference", "decision_policy"}),
        budget=600,
        format=FORMAT_EVIDENCE,
        include_person=True,
        person_kinds=ALL_MEMORY_KINDS,
        person_budget=400,
    ),
    "summarize-week": PurposePolicy(
        kinds=frozenset({"preference", "decision_policy", "pattern"}),
        budget=800,
        format=FORMAT_EVIDENCE,
        include_person=True,
        person_kinds=ALL_MEMORY_KINDS,
        person_budget=500,
    ),
    "summarize-month": PurposePolicy(
        kinds=frozenset({"preference", "decision_policy", "pattern"}),
        budget=500,
        format=FORMAT_EVIDENCE,
        include_person=False,
    ),
    "review-draft": PurposePolicy(
        kinds=frozenset({"preference", "decision_policy"}),
        budget=400,
        format=FORMAT_FENCED,
        include_person=False,
    ),
}


def get_builtin_policy(for_purpose: str) -> PurposePolicy:
    return _BUILTIN_POLICIES.get(for_purpose, _DEFAULT_POLICY)


def _coerce_kinds(raw: object) -> frozenset[str] | None:
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return None
    kinds = frozenset(str(k) for k in raw if str(k) in ALL_MEMORY_KINDS)
    return kinds or None


def _coerce_budget(raw: object) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def resolve_policy(for_purpose: str) -> PurposePolicy:
    """Return the effective policy for ``for_purpose``.

    Starts from the built-in policy and applies any matching
    ``memory.purposes.<purpose>`` override from config.
    """
    policy = get_builtin_policy(for_purpose)
    overrides = getattr(config, "MEMORY_PURPOSE_OVERRIDES", {}) or {}
    raw = overrides.get(for_purpose) if isinstance(overrides, dict) else None
    if not isinstance(raw, dict):
        return policy

    kinds = policy.kinds
    if "kinds" in raw:
        coerced_kinds = _coerce_kinds(raw["kinds"])
        if coerced_kinds is not None:
            kinds = coerced_kinds

    budget = policy.budget
    if "budget" in raw:
        coerced_budget = _coerce_budget(raw["budget"])
        if coerced_budget is not None:
            budget = coerced_budget

    fmt = raw.get("format", policy.format)
    if fmt not in ALLOWED_FORMATS:
        fmt = policy.format

    include_person = raw.get("include_person", policy.include_person)

    person_kinds = policy.person_kinds
    if "person_kinds" in raw:
        coerced_person_kinds = _coerce_kinds(raw["person_kinds"])
        if coerced_person_kinds is not None:
            person_kinds = coerced_person_kinds

    person_budget = policy.person_budget
    if "person_budget" in raw:
        coerced_person_budget = _coerce_budget(raw["person_budget"])
        if coerced_person_budget is not None:
            person_budget = coerced_person_budget

    return replace(
        policy,
        kinds=kinds,
        budget=budget,
        format=fmt,
        include_person=bool(include_person),
        person_kinds=person_kinds,
        person_budget=person_budget,
    )
