"""Domain-scoped MCP server over the AMO situations graph.

Each domain in DOMAINS is served at its own path (`/amo/mcp`) as an independent
MCPServer that only ever sees its own domain's nodes. This repo ships one
domain; the per-path isolation is the seam for adding another.
"""
