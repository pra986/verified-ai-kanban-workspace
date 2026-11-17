from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from kanban_app.models import (
    CardMutationProposal,
    CardOperationReceipt,
    KanbanCard,
    MutationAction,
)


class KanbanValidationError(ValueError):
    """Raised when a card or column validation check fails."""


class UnauthorizedBoardAccessError(PermissionError):
    """Raised when an actor attempts to mutate or read an unauthorized board."""


class VerifiedKanbanEngine:
    """Shared SQLite-backed Kanban engine for manual and AI card mutations."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS boards (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    title TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS board_members (
                    board_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    PRIMARY KEY (board_id, actor_id),
                    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS columns (
                    id TEXT PRIMARY KEY,
                    board_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS cards (
                    id TEXT PRIMARY KEY,
                    board_id TEXT NOT NULL,
                    column_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'medium',
                    assignee TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
                    FOREIGN KEY (column_id) REFERENCES columns(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS operation_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    board_id TEXT NOT NULL,
                    card_id TEXT,
                    action TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    committed INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        self._conn.close()

    def create_board(
        self,
        board_id: str,
        owner_id: str,
        title: str,
        column_ids: Optional[List[str]] = None,
    ) -> None:
        cols = column_ids or ["todo", "in_progress", "done"]
        with self._conn:
            self._conn.execute(
                "INSERT INTO boards (id, owner_id, title) VALUES (?, ?, ?)",
                (board_id, owner_id, title),
            )
            self._conn.execute(
                "INSERT INTO board_members (board_id, actor_id) VALUES (?, ?)",
                (board_id, owner_id),
            )
            for idx, col_id in enumerate(cols):
                self._conn.execute(
                    "INSERT INTO columns (id, board_id, title, position) VALUES (?, ?, ?, ?)",
                    (col_id, board_id, col_id.replace("_", " ").title(), idx),
                )

    def grant_access(self, board_id: str, actor_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO board_members (board_id, actor_id) VALUES (?, ?)",
                (board_id, actor_id),
            )

    def _assert_board_access(self, board_id: str, actor_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM board_members WHERE board_id = ? AND actor_id = ?",
            (board_id, actor_id),
        ).fetchone()
        if row is None:
            raise UnauthorizedBoardAccessError(
                f"Actor '{actor_id}' is not authorized for board '{board_id}'."
            )

    def _assert_valid_column(self, board_id: str, column_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM columns WHERE id = ? AND board_id = ?",
            (column_id, board_id),
        ).fetchone()
        if row is None:
            raise KanbanValidationError(
                f"Column '{column_id}' does not exist on board '{board_id}'."
            )

    def _get_card_row(self, board_id: str, card_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM cards WHERE id = ? AND board_id = ?",
            (card_id, board_id),
        ).fetchone()
        if row is None:
            raise KanbanValidationError(
                f"Card '{card_id}' does not exist on board '{board_id}'."
            )
        return row

    @staticmethod
    def _row_to_card(row: sqlite3.Row) -> KanbanCard:
        return KanbanCard(
            id=row["id"],
            board_id=row["board_id"],
            column_id=row["column_id"],
            title=row["title"],
            description=row["description"],
            position=row["position"],
            priority=row["priority"],
            assignee=row["assignee"],
            updated_at=row["updated_at"],
        )

    def _reindex_column(self, board_id: str, column_id: str) -> None:
        rows = self._conn.execute(
            "SELECT id FROM cards WHERE board_id = ? AND column_id = ? ORDER BY position ASC, updated_at ASC",
            (board_id, column_id),
        ).fetchall()
        for idx, r in enumerate(rows):
            self._conn.execute(
                "UPDATE cards SET position = ? WHERE id = ?",
                (idx, r["id"]),
            )

    def list_cards(self, board_id: str, actor_id: str) -> Dict[str, List[KanbanCard]]:
        self._assert_board_access(board_id, actor_id)
        cols = self._conn.execute(
            "SELECT id FROM columns WHERE board_id = ? ORDER BY position ASC",
            (board_id,),
        ).fetchall()
        result: Dict[str, List[KanbanCard]] = {c["id"]: [] for c in cols}
        cards = self._conn.execute(
            "SELECT * FROM cards WHERE board_id = ? ORDER BY column_id ASC, position ASC",
            (board_id,),
        ).fetchall()
        for row in cards:
            result.setdefault(row["column_id"], []).append(self._row_to_card(row))
        return result

    def apply_mutation(self, proposal: CardMutationProposal) -> CardOperationReceipt:
        self._assert_board_access(proposal.board_id, proposal.actor_id)

        if proposal.idempotency_key:
            existing = self._conn.execute(
                "SELECT * FROM operation_receipts WHERE idempotency_key = ?",
                (proposal.idempotency_key,),
            ).fetchone()
            if existing is not None:
                card_obj = None
                if existing["card_id"]:
                    c_row = self._conn.execute(
                        "SELECT * FROM cards WHERE id = ?",
                        (existing["card_id"],),
                    ).fetchone()
                    if c_row is not None:
                        card_obj = self._row_to_card(c_row)
                return CardOperationReceipt(
                    receipt_id=existing["receipt_id"],
                    status=existing["status"],
                    action=existing["action"],
                    board_id=existing["board_id"],
                    card_id=existing["card_id"],
                    source=existing["source"],
                    committed=bool(existing["committed"]),
                    idempotent_replay=True,
                    message=f"Idempotent replay: {existing['message']}",
                    card=card_obj,
                    timestamp=existing["timestamp"],
                )

        now = datetime.now(timezone.utc).isoformat()
        receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"

        with self._conn:
            if proposal.action == MutationAction.CREATE:
                if not proposal.target_column_id:
                    raise KanbanValidationError("target_column_id is required for CREATE.")
                if not proposal.title:
                    raise KanbanValidationError("title is required for CREATE.")
                self._assert_valid_column(proposal.board_id, proposal.target_column_id)
                card_id = proposal.card_id or f"card-{uuid.uuid4().hex[:8]}"
                count_row = self._conn.execute(
                    "SELECT COUNT(*) AS cnt FROM cards WHERE board_id = ? AND column_id = ?",
                    (proposal.board_id, proposal.target_column_id),
                ).fetchone()
                pos = (
                    proposal.target_position
                    if proposal.target_position is not None
                    else int(count_row["cnt"])
                )
                self._conn.execute(
                    """
                    INSERT INTO cards (id, board_id, column_id, title, description, position, priority, assignee, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card_id,
                        proposal.board_id,
                        proposal.target_column_id,
                        proposal.title,
                        proposal.description or "",
                        pos,
                        proposal.priority or "medium",
                        proposal.assignee,
                        now,
                    ),
                )
                self._reindex_column(proposal.board_id, proposal.target_column_id)
                msg = f"Created card '{card_id}' in '{proposal.target_column_id}'."

            elif proposal.action == MutationAction.MOVE:
                if not proposal.card_id or not proposal.target_column_id:
                    raise KanbanValidationError("card_id and target_column_id are required for MOVE.")
                card_row = self._get_card_row(proposal.board_id, proposal.card_id)
                self._assert_valid_column(proposal.board_id, proposal.target_column_id)
                source_col = card_row["column_id"]

                dest_rows = self._conn.execute(
                    "SELECT id FROM cards WHERE board_id = ? AND column_id = ? AND id != ? ORDER BY position ASC",
                    (proposal.board_id, proposal.target_column_id, proposal.card_id),
                ).fetchall()
                ordered_ids = [r["id"] for r in dest_rows]
                insert_idx = (
                    len(ordered_ids)
                    if proposal.target_position is None
                    else max(0, min(proposal.target_position, len(ordered_ids)))
                )
                ordered_ids.insert(insert_idx, proposal.card_id)

                self._conn.execute(
                    "UPDATE cards SET column_id = ?, updated_at = ? WHERE id = ?",
                    (proposal.target_column_id, now, proposal.card_id),
                )
                for idx, cid in enumerate(ordered_ids):
                    self._conn.execute(
                        "UPDATE cards SET position = ? WHERE id = ?",
                        (idx, cid),
                    )
                if source_col != proposal.target_column_id:
                    self._reindex_column(proposal.board_id, source_col)
                card_id = proposal.card_id
                msg = f"Moved card '{card_id}' to '{proposal.target_column_id}' at position {insert_idx}."

            elif proposal.action == MutationAction.UPDATE:
                if not proposal.card_id:
                    raise KanbanValidationError("card_id is required for UPDATE.")
                card_row = self._get_card_row(proposal.board_id, proposal.card_id)
                self._conn.execute(
                    """
                    UPDATE cards
                    SET title = ?, description = ?, priority = ?, assignee = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        proposal.title if proposal.title is not None else card_row["title"],
                        proposal.description if proposal.description is not None else card_row["description"],
                        proposal.priority if proposal.priority is not None else card_row["priority"],
                        proposal.assignee if proposal.assignee is not None else card_row["assignee"],
                        now,
                        proposal.card_id,
                    ),
                )
                card_id = proposal.card_id
                msg = f"Updated card '{card_id}'."

            elif proposal.action == MutationAction.DELETE:
                if not proposal.card_id:
                    raise KanbanValidationError("card_id is required for DELETE.")
                card_row = self._get_card_row(proposal.board_id, proposal.card_id)
                col_id = card_row["column_id"]
                self._conn.execute("DELETE FROM cards WHERE id = ?", (proposal.card_id,))
                self._reindex_column(proposal.board_id, col_id)
                card_id = proposal.card_id
                msg = f"Deleted card '{card_id}'."
            else:
                raise KanbanValidationError(f"Unsupported action: {proposal.action}")

            self._conn.execute(
                """
                INSERT INTO operation_receipts
                (receipt_id, idempotency_key, board_id, card_id, action, source, status, committed, message, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    proposal.idempotency_key,
                    proposal.board_id,
                    card_id,
                    proposal.action.value,
                    proposal.source.value,
                    "committed",
                    1,
                    msg,
                    now,
                ),
            )

        updated_card = None
        if proposal.action != MutationAction.DELETE:
            c_row = self._conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
            if c_row is not None:
                updated_card = self._row_to_card(c_row)

        return CardOperationReceipt(
            receipt_id=receipt_id,
            status="committed",
            action=proposal.action.value,
            board_id=proposal.board_id,
            card_id=card_id,
            source=proposal.source.value,
            committed=True,
            idempotent_replay=False,
            message=msg,
            card=updated_card,
            timestamp=now,
        )
