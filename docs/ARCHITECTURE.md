# Architecture: Verified AI Kanban Workspace

## Core Design Principle

Both manual UI drag-and-drop actions and AI-proposed card mutations (via OpenRouter) are untrusted proposals until validated and committed by `VerifiedKanbanEngine` against SQLite.

## System Layers

1. **Presentation Layer (Next.js)**:
   - Renders boards, columns, and contiguously ordered cards.
   - Emits `CardMutationProposal` payloads on drag-and-drop or AI tool-call approval.
   - Displays mutation status only after receiving a `CardOperationReceipt`.

2. **API Gateway (FastAPI)**:
   - Authenticates actor identity (`actor_id`) and forwards `CardMutationProposal` objects to `VerifiedKanbanEngine`.
   - Rejects malformed payloads via Pydantic v2 schemas.

3. **Verification & State Engine (`kanban_app/engine.py`)**:
   - **Board Access Control**: Confirms `actor_id` is an authorized member/owner of `board_id`.
   - **ID Validation**: Verifies `card_id` belongs to `board_id` and `target_column_id` exists on `board_id`.
   - **Idempotency**: Persists `operation_id` receipts in `operation_receipts` so duplicate moves return `"duplicate"` without mutating card positions again.
   - **Contiguous Ordering**: Re-indexes all cards in affected columns to `0, 1, ..., n-1` within a single SQLite transaction.

4. **SQLite Persistence**:
   - Tables: `boards`, `board_members`, `columns`, `cards`, `operation_receipts`.
   - Foreign keys enabled (`PRAGMA foreign_keys = ON`) for referential integrity across refreshes.
