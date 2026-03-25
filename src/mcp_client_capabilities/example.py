"""
Simple example of using the MCP Client Capabilities index
"""

import json

from . import mcp_clients

print("=== MCP Client Capabilities ===\n")

# Access Claude Desktop capabilities directly
print("Claude Desktop capabilities:")
print(json.dumps(mcp_clients["claude-ai"], indent=2))
print()

# List all available clients
print("Available clients:", list(mcp_clients.keys()))
print()

# Check specific capabilities
claude_desktop = mcp_clients.get("claude-ai")
if claude_desktop:
    prompts = claude_desktop.get("prompts")
    if prompts and prompts.get("listChanged"):
        print("✓ Claude Desktop supports prompts list change notifications")
    else:
        print("✗ Claude Desktop does not support prompts list change notifications")

    resources = claude_desktop.get("resources")
    if resources and resources.get("subscribe"):
        print("✓ Claude Desktop supports resource subscriptions")
    else:
        print("✗ Claude Desktop does not support resource subscriptions")

    tools = claude_desktop.get("tools")
    if tools and tools.get("listChanged"):
        print("✓ Claude Desktop supports tools list change notifications")
    else:
        print("✗ Claude Desktop does not support tools list change notifications")
else:
    print("❌ Claude Desktop client not found")
