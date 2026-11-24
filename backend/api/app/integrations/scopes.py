"""The permissions a school admin can grant an integration (ADR 0008 decision 4).

Scope names are `resource:action`. Only names in this catalogue can be granted. The endpoints that
use them are in `app/integrations/public.py` (Integrations C), and webhook events are sent only
for the scopes an integration holds (`app/integrations/events.py`).
"""

SCOPES: dict[str, str] = {
    "classes:read": "Read the school's sessions, terms, classes and subjects.",
    "candidates:read": "Look up students and the classes they're enrolled in.",
    "candidates:write": "Add and update students and their class enrolment.",
    "results:read": "Read results once they're released to students.",
    "exams:read": "See published exams: title, subject, classes and times, never the questions.",
}


def unknown_scopes(names: list[str]) -> list[str]:
    return sorted({name for name in names if name not in SCOPES})
