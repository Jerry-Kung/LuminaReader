from __future__ import annotations

from typing import Protocol


class Migration(Protocol):
    target_version: int
    description: str

    def apply(self, conn) -> None: ...
