"""
TypeScript interfaces for Model Context Protocol (MCP) client capabilities
"""

from typing import TypedDict


class Resources(TypedDict, total=False):
    list_changed: bool | None
    subscribe: bool | None


class Prompts(TypedDict, total=False):
    list_changed: bool | None


class Tools(TypedDict, total=False):
    list_changed: bool | None


class Roots(TypedDict, total=False):
    list_changed: bool | None


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


class McpClientRecord(TypedDict):
    title: str
    url: str
    protocol_version: str
    resources: Resources | None
    prompts: Prompts | None
    tools: Tools | None
    elicitation: Elicitation | None
    sampling: Sampling | None
    roots: Roots | None
    completions: Completions | None
    logging: Logging | None
    experimental: Experimental | None


ClientsIndex = dict[str, McpClientRecord]
