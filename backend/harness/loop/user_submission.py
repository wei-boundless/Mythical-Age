from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Literal


UserSubmissionKind = Literal["user_input", "continue", "pause", "stop", "approval", "system_resume"]


@dataclass(frozen=True, slots=True)
class UserSubmission:
    submission_id: str
    session_id: str
    turn_id: str
    source: str
    kind: UserSubmissionKind
    content: str
    created_at: float
    client_message_id: str = ""
    authority: str = "runtime.user_submission"

    def __post_init__(self) -> None:
        if self.authority != "runtime.user_submission":
            raise ValueError("UserSubmission authority must be runtime.user_submission")
        if not self.submission_id:
            raise ValueError("UserSubmission requires submission_id")
        if not self.session_id:
            raise ValueError("UserSubmission requires session_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_user_submission(
    *,
    session_id: str,
    content: str,
    turn_id: str = "",
    source: str = "conversation",
    kind: UserSubmissionKind = "user_input",
    client_message_id: str = "",
) -> UserSubmission:
    return UserSubmission(
        submission_id=f"submission:{uuid.uuid4().hex}",
        session_id=str(session_id or "").strip(),
        turn_id=str(turn_id or "").strip(),
        source=str(source or "conversation").strip() or "conversation",
        kind=kind,
        content=str(content or ""),
        client_message_id=str(client_message_id or "").strip(),
        created_at=time.time(),
    )
