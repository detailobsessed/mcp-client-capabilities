"""
TypeScript interfaces for Model Context Protocol (MCP) client capabilities
"""

from typing import TypedDict


class Resources(TypedDict, total=False):
    listChanged: bool | None
    subscribe: bool | None


class Prompts(TypedDict, total=False):
    listChanged: bool | None


class Tools(TypedDict, total=False):
    listChanged: bool | None


class Roots(TypedDict, total=False):
    listChanged: bool | None


class Completions(TypedDict, total=False):
    pass


class Logging(TypedDict, total=False):
    pass


class Experimental(TypedDict, total=False):
    pass


class Elicitation(TypedDict, total=False):
    pass


class Sampling(TypedDict, total=False):
    pass


class Tasks(TypedDict, total=False):
    pass


class _McpClientRecordRequired(TypedDict):
    title: str
    url: str
    protocolVersion: str


class McpClientRecord(_McpClientRecordRequired, total=False):
    resources: Resources
    prompts: Prompts
    tools: Tools
    elicitation: Elicitation
    sampling: Sampling
    roots: Roots
    completions: Completions
    logging: Logging
    experimental: Experimental
    tasks: Tasks


ClientsIndex = dict[str, McpClientRecord]
