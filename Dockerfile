# Dockerfile — for Glama (glama.ai) introspection and scoring ONLY.
#
# TheWeave is local-first: in real use you run the MCP server on your own
# machine, against your own markdown vault (see README / Quickstart). You do
# NOT need Docker to use it. This image exists so directory services can start
# the server against the bundled seed-vault and list its tools over stdio.
FROM python:3.11-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .

# Point the server at the bundled demo vault so it can start for introspection.
ENV WEAVE_VAULT_PATH=/app/seed-vault

# Weave Core MCP server, stdio transport.
ENTRYPOINT ["python", "-m", "weave.mcp_server"]
