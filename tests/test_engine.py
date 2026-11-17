import pytest

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


def test_invalid_column_id_rejected(tmp_path):
    db_file = str(tmp_path / "kanban.db")
    engine = VerifiedKanbanEngine(db_file)
    engine.create_board("b1", "owner1", "Finance Board", ["todo", "doing", "done"])

    with pytest.raises(KanbanValidationError, match="does not exist"):
        engine.apply_mutation(
            CardMutationProposal(
                action=MutationAction.CREATE,
                board_id="b1",
                actor_id="owner1",
                source=MutationSource.AI,
                target_column_id="ghost_column",
                title="Invalid card",
            )
        )
    engine.close()


def test_card_order_persists_across_refresh(tmp_path):
    db_file = str(tmp_path / "kanban.db")
    engine = VerifiedKanbanEngine(db_file)
    engine.create_board("b1", "owner1", "Finance Board", ["todo", "done"])

    engine.apply_mutation(
        CardMutationProposal(
            action=MutationAction.CREATE,
            board_id="b1",
            actor_id="owner1",
            source=MutationSource.MANUAL,
            card_id="c1",
            target_column_id="todo",
            title="First",
        )
    )
    engine.apply_mutation(
        CardMutationProposal(
            action=MutationAction.CREATE,
            board_id="b1",
            actor_id="owner1",
            source=MutationSource.MANUAL,
            card_id="c2",
            target_column_id="todo",
            title="Second",
        )
    )
    engine.apply_mutation(
        CardMutationProposal(
            action=MutationAction.MOVE,
            board_id="b1",
            actor_id="owner1",
            source=MutationSource.MANUAL,
            card_id="c2",
            target_column_id="todo",
            target_position=0,
        )
    )
    engine.close()

    refreshed = VerifiedKanbanEngine(db_file)
    columns = refreshed.list_cards("b1", "owner1")
    assert [c.id for c in columns["todo"]] == ["c2", "c1"]
    assert [c.position for c in columns["todo"]] == [0, 1]
    refreshed.close()


def test_unauthorized_board_access_rejected(tmp_path):
    db_file = str(tmp_path / "kanban.db")
    engine = VerifiedKanbanEngine(db_file)
    engine.create_board("b1", "owner1", "Finance Board", ["todo", "done"])

    with pytest.raises(UnauthorizedBoardAccessError):
        engine.list_cards("b1", "unauthorized_user")

    with pytest.raises(UnauthorizedBoardAccessError):
        engine.apply_mutation(
            CardMutationProposal(
                action=MutationAction.CREATE,
                board_id="b1",
                actor_id="unauthorized_user",
                source=MutationSource.AI,
                target_column_id="todo",
                title="Unauthorized card",
            )
        )
    engine.close()


def test_idempotent_duplicate_move_handling(tmp_path):
    db_file = str(tmp_path / "kanban.db")
    engine = VerifiedKanbanEngine(db_file)
    engine.create_board("b1", "owner1", "Finance Board", ["todo", "done"])
    engine.apply_mutation(
        CardMutationProposal(
            action=MutationAction.CREATE,
            board_id="b1",
            actor_id="owner1",
            source=MutationSource.MANUAL,
            card_id="c1",
            target_column_id="todo",
            title="Audit ledger",
        )
    )

    move_proposal = CardMutationProposal(
        action=MutationAction.MOVE,
        board_id="b1",
        actor_id="owner1",
        source=MutationSource.AI,
        card_id="c1",
        target_column_id="done",
        target_position=0,
        idempotency_key="move-c1-done-001",
    )
    first_receipt = engine.apply_mutation(move_proposal)
    second_receipt = engine.apply_mutation(move_proposal)

    assert first_receipt.committed is True
    assert first_receipt.idempotent_replay is False
    assert second_receipt.committed is True
    assert second_receipt.idempotent_replay is True
    assert second_receipt.receipt_id == first_receipt.receipt_id
    columns = engine.list_cards("b1", "owner1")
    assert [c.id for c in columns["done"]] == ["c1"]
    engine.close()
