"""Agent tool base class."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.agents.core import AgentContext


class Tool:
    """Agent tool base class. Subclasses set name/description/input_model and implement execute."""

    name: str = ""
    description: str = ""
    input_model: type[BaseModel]

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        raise NotImplementedError
