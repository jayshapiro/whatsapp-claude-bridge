from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """Base class for all tools available to Claude."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def input_schema(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        ...

    @property
    def requires_approval(self) -> bool:
        return False

    def check_approval(self, **kwargs) -> bool:
        """Check whether this specific invocation requires approval.

        Override in subclasses for input-dependent approval logic.
        Falls back to the static `requires_approval` property.
        """
        return self.requires_approval

    def to_api_dict(self) -> Dict[str, Any]:
        """Return the Anthropic tool-definition dict."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
