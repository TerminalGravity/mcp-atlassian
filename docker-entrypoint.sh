#!/bin/bash
set -e

echo "=== MCP Atlassian Backend ==="

# Check if sync should run
if [ "${SKIP_SYNC:-false}" = "true" ]; then
    echo "Skipping vector sync (SKIP_SYNC=true)"
else
    # Check if vector DB exists and has data
    if [ -d "/app/data/lancedb" ] && [ "$(ls -A /app/data/lancedb 2>/dev/null)" ]; then
        echo "Vector DB exists, running incremental sync..."
        uv run python -m mcp_atlassian.vector.cli sync || echo "Sync failed, continuing anyway..."
    else
        echo "No vector DB found, running full sync..."
        PROJECTS="${VECTOR_SYNC_PROJECTS:-DS}"
        echo "Syncing projects: $PROJECTS"
        uv run python -m mcp_atlassian.vector.cli sync --full --projects "$PROJECTS" || echo "Sync failed, continuing anyway..."
    fi
fi

echo "Starting FastAPI server..."
exec uv run uvicorn mcp_atlassian.web.server:app --host 0.0.0.0 --port 8000
