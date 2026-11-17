from __future__ import annotations

import json
from dataclasses import asdict

from kanban_app.engine import (
    KanbanValidationError,
    UnauthorizedBoardAccessError,
    VerifiedKanbanEngine,
)
from kanban_app.models import (
    CardMutationProposal,
    MutationAction,
    MutationSource,
)


def run_demo() -> None:
    engine = VerifiedKanbanEngine(":memory:")
    board_id = "board-finance-q4"
    owner_id = "user-pranil"
    engine.create_board(
        board_id=board_id,
        owner_id=owner_id,
        title="Q4 Finance Operations",
        column_ids=["backlog", "in_progress", "review", "done"],
    )

    c1 = engine.apply_mutation(
        CardMutationProposal(
            action=MutationAction.CREATE,
            board_id=board_id,
            actor_id=owner_id,
            source=MutationSource.MANUAL,
            card_id="card-101",
            target_column_id="backlog",
            title="Reconcile vendor invoices",
            priority="high",
        )
    )
    print("CREATE receipt:", json.dumps(asdict(c1), indent=2))

    m1 = engine.apply_mutation(
        CardMutationProposal(
            action=MutationAction.MOVE,
            board_id=board_id,
            actor_id=owner_id,
            source=MutationSource.AI,
            card_id="card-101",
            target_column_id="in_progress",
            target_position=0,
            idempotency_key="demo-move-101",
        )
    )
    print("AI MOVE receipt:", json.dumps(asdict(m1), indent=2))

    replay = engine.apply_mutation(
        CardMutationProposal(
            action=MutationAction.MOVE,
            board_id=board_id,
            actor_id=owner_id,
            source=MutationSource.AI,
            card_id="card-101",
            target_column_id="in_progress",
            target_position=0,
            idempotency_key="demo-move-101",
        )
    )
    print("IDEMPOTENT REPLAY:", replay.idempotent_replay, replay.receipt_id)

    try:
        engine.apply_mutation(
            CardMutationProposal(
                action=MutationAction.MOVE,
                board_id=board_id,
                actor_id=owner_id,
                source=MutationSource.AI,
                card_id="card-101",
                target_column_id="nonexistent_col",
            )
        )
    except KanbanValidationError as exc:
        print("Blocked invalid column:", exc)

    try:
        engine.list_cards(board_id=board_id, actor_id="intruder")
    except UnauthorizedBoardAccessError as exc:
        print("Blocked unauthorized access:", exc)

    engine.close()


if __name__ == "__main__":
    run_demo()
