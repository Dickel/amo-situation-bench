# Image for the MCP server (/amo/mcp). Does NOT bundle Memgraph — it reaches
# Memgraph over Fly's private network via the neo4j Bolt driver.
FROM python:3.12-slim

WORKDIR /app

COPY mcp_server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server/ ./mcp_server/

# MEMGRAPH_URI + DOMAINS/DOMAIN come from fly.mcp.toml [env]. MCP_PORT matches
# the fly.toml internal_port.
ENV MCP_HOST=0.0.0.0 MCP_PORT=8000
EXPOSE 8000

CMD ["python", "-m", "mcp_server"]
