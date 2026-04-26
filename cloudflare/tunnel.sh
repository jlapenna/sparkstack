#!/usr/bin/env bash
# Cloudflare Tunnel helper - passes parent .env to docker compose

set -e

CDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_ENV="${CDIR}/../.env"

if [[ ! -f "$PARENT_ENV" ]]; then
  echo "❌ Error: Parent .env file not found at $PARENT_ENV"
  exit 1
fi

docker compose --env-file "$PARENT_ENV" "$@"

# Verification Step: If 'up' was called, verify the container is actually running
if [[ "$*" == *"up"* ]]; then
  echo "🔍 Verifying cloudflared startup..."
  sleep 2
  if docker ps --format '{{.Names}}' | grep -q "^cloudflared$"; then
    TOKEN_CHECK=$(docker inspect cloudflared --format '{{range .Config.Env}}{{println .}}{{end}}' | grep "TUNNEL_TOKEN=" | cut -d'=' -f2)
    if [[ -z "$TOKEN_CHECK" ]]; then
      echo "❌ Error: cloudflared is running but TUNNEL_TOKEN is empty!"
      exit 1
    else
      echo "✅ cloudflared is running with a valid TUNNEL_TOKEN."
    fi
  else
    echo "❌ Error: cloudflared container failed to start."
    docker logs cloudflared | tail -n 5
    exit 1
  fi
fi
