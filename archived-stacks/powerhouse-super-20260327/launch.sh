#!/bin/bash
set -e
CDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_ENV="${CDIR}/../../.env"

if [[ ! -f "$PARENT_ENV" ]]; then
  echo "❌ Error: Root .env file not found at $PARENT_ENV"
  exit 1
fi

# Export env vars for tool interpolation and execution
set -a
source "$PARENT_ENV"
set +a

echo "🚀 Launching model instances via sparkrun..."
sparkrun run /home/jlapenna/services/vllm/spark-stack-registry/models/nemotron-super.yaml --hosts localhost --port 8001 --solo --no-follow --tp 1 -o port=8000 -o host=0.0.0.0 --tp 1 --gpu-mem 0.7 --max-model-len 65536

echo "📦 Starting gateway and monitoring via docker compose..."
docker compose --env-file "$PARENT_ENV" up -d
echo "✅ Stack is operational."