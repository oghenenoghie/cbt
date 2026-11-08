# AI Question Generation Engine

**Implemented inside the API** (`backend/api/app/ai/`, ADR 0005): retrieval in `retrieval.py`, the provider adapter in `provider.py` (Claude in `claude.py`, a deterministic fake in `fake.py`), the checks in `checks.py`, and the queue in `processing.py`. Question types so far: single-answer multiple choice and true/false.

The engine generates candidate questions only from retrieved passages belonging to approved school document versions.

Required pipeline:
1. Accept a scoped generation request (school, subject, topic, approved document IDs, question types, count, difficulty and marks).
2. Retrieve relevant passages from the permitted source set only.
3. Generate schema-constrained candidate questions with passage/page citations.
4. Validate every factual claim and expected answer against cited evidence.
5. Reject unsupported, out-of-scope, duplicate or ambiguous candidates.
6. Return accepted drafts, rejected candidates with reasons, and an evidence-shortfall report.

The model provider must be replaceable behind an adapter. Never let model-generated statements or citations bypass server-side verification. No internet search or unrestricted model knowledge is used as question source material.
