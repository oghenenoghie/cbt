"""The permissions a school admin can grant an integration (ADR 0008 decision 4).

Scope names are `resource:action`. Only names in this catalogue can be granted. The endpoints that
use them are in `app/integrations/public.py` (Integrations C).
"""

SCOPES: dict[str, str] = {
    "classes:read": "Read the school's sessions, terms, classes and subjects.",
    "candidates:read": "Look up students and the classes they're enrolled in.",
    "candidates:write": "Add and update students and their class enrolment.",
    "results:read": "Read results once they're released to students.",
}


def unknown_scopes(names: list[str]) -> list[str]:
    return sorted({name for name in names if name not in SCOPES})
