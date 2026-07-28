"""
biz_mcp/registry.py — MCP Server Registry for dynamic registration.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


@dataclass
class MCPServerDef:
    identifier: str
    name: str
    description: str = ""
    tools: List[ToolDef] = field(default_factory=list)
    config_schema: dict = field(default_factory=dict)


class MCPRegistry:
    """
    Singleton registry for MCP Server definitions.
    Third-party MCP packages call MCPRegistry.register() at startup
    to expose their tools and configuration schemas.
    """
    _servers: Dict[str, MCPServerDef] = {}

    @classmethod
    def register(
        cls,
        identifier: str,
        name: str,
        description: str = "",
        tools: List[ToolDef] = None,
        config_schema: dict = None,
    ) -> None:
        cls._servers[identifier] = MCPServerDef(
            identifier=identifier,
            name=name,
            description=description,
            tools=tools or [],
            config_schema=config_schema or {},
        )

    @classmethod
    def get(cls, identifier: str) -> Optional[MCPServerDef]:
        return cls._servers.get(identifier)

    @classmethod
    def list_all(cls) -> Dict[str, MCPServerDef]:
        return cls._servers.copy()

    @classmethod
    def list_identifiers(cls) -> List[str]:
        return list(cls._servers.keys())
