# verified-ai-kanban-workspace

Project 13: Persistent AI Kanban workspace routing manual drag-and-drop and OpenRouter AI card mutations through a shared SQLite validation layer.

## Architecture Overview

`verified-ai-kanban-workspace` separates **proposal generation** (manual UI drag-and-drop or OpenRouter LLM tool calls) from **state mutation** (`VerifiedKanbanEngine` backed by SQLite). Both manual and AI-initiated card operations pass through the exact same validation, authorization, idempotency, and contiguous-ordering pipeline before any database commit occurs.

- **Frontend (Next.js)**: Optimistic board UI with manual drag-and-drop and AI assistant chat panel, reconciled against server-issued `CardOperationReceipt` records.
- **API Layer (FastAPI)**: REST endpoints for board reads, manual card moves, and OpenRouter-powered AI card mutation proposals.
- **Core Engine (`kanban_app/engine.py`)**: `VerifiedKanbanEngine` enforcing board membership/ownership checks, valid card and column ID validation, idempotency keys, contiguous 0-indexed card ordering, and SQLite transactional persistence.
- **Persistence (SQLite)**: Single-source-of-truth relational schema (`boards`, `columns`, `cards`, `operation_receipts`) ensuring card order survives page refreshes.

## 6-Stage Verified Mutation Workflow

1. **Intent / Proposal**: User drags a card or submits a natural-language prompt to the OpenRouter AI assistant, producing a `CardMutationProposal`.
2. **Authorization Check**: Engine verifies the actor is authorized for the target `board_id`, rejecting unauthorized cross-board access.
3. **Schema & Reference Validation**: Engine validates that `card_id` exists on the board and `target_column_id` is a valid column on that board.
4. **Idempotency Deduplication**: Engine checks `operation_id` against `operation_receipts`; duplicate requests return the original receipt without re-applying side effects.
5. **Transactional Reorder & Commit**: Inside an atomic SQLite transaction, the card is moved and source/target columns are re-indexed to contiguous positions (`0..N-1`).
6. **Receipt Verification**: Engine returns a signed/persisted `CardOperationReceipt` (`status="applied"` or `"duplicate"`). UI and AI assistant may only claim success after receiving this receipt.

## Data Contract

- **`KanbanCard`**: `card_id`, `board_id`, `column_id`, `title`, `description`, `position`, `updated_at`
- **`CardMutationProposal`**: `operation_id`, `board_id`, `actor_id`, `source` (`"manual"` | `"ai"`), `action` (`"create"` | `"move"` | `"update"` | `"delete"`), `card_id`, `target_column_id`, `target_position`, `title`, `description`
- **`CardOperationReceipt`**: `operation_id`, `board_id`, `card_id`, `status` (`"applied"` | `"duplicate"` | `"rejected"`), `column_id`, `position`, `message`, `timestamp`

## Production Controls

- **Shared Validation Gate**: AI mutations cannot bypass column/card foreign-key or authorization checks.
- **Receipt-Before-Claim**: AI responses are grounded in `CardOperationReceipt` outputs rather than unverified LLM assumptions.
- **Idempotent Retries**: Network retries or duplicate tool calls with the same `operation_id` are safely deduplicated.
- **Contiguous Ordering**: Every move/delete normalizes `position` values (`0, 1, 2, ...`) in SQLite so board order is deterministic across refreshes.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m kanban_app.cli
pytest -v
```

## Attribution

Inspired by and pinned to [ed-donner/pm](https://github.com/ed-donner/pm).

## License

MIT License — see [LICENSE](LICENSE). shared SQLite validation layer.
