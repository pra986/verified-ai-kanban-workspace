from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class MutationSource(str, Enum):
    MANUAL = "manual"
    AI = "ai"


class MutationAction(str, Enum):
    CREATE = "create"
    MOVE = "move"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True)
class KanbanCard:
    id: str
    board_id: str
    column_id: str
    title: str
    description: str = ""
    position: int = 0
    priority: str = "medium"
    assignee: Optional[str] = None
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class CardMutationProposal:
    action: MutationAction
    board_id: str
    actor_id: str
    source: MutationSource = MutationSource.AI
    card_id: Optional[str] = None
    target_column_id: Optional[str] = None
    target_position: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass(frozen=True)
class CardOperationReceipt:
    receipt_id: str
    status: str
    action: str
    board_id: str
    card_id: Optional[str]
    source: str
    committed: bool
    idempotent_replay: bool = False
    message: str = ""
    card: Optional[KanbanCard] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
