#!/bin/bash
set -e
CDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_ENV="${CDIR}/../../.env"

if [[ ! -f "$PARENT_ENV" ]]; then
  echo "⚠️ Warning: Root .env file not found at $PARENT_ENV, using empty env"
  touch "$PARENT_ENV" || true
fi
set -a
source "$PARENT_ENV" 2>/dev/null || true
set +a

echo "🧹 Cleaning up old containers..."
docker rm -f vllm-gateway vllm-progress main_solo embedding_solo 2>/dev/null || true
docker compose --env-file "$PARENT_ENV" -f "$CDIR/docker-compose.yaml" down --remove-orphans 2>/dev/null || true
sleep 2

echo "🚀 Launching model instances via sparkrun..."
uv \
  run \
  sparkrun \
  run \
  /home/jlapenna/services/registry/models/qwen3.6-35b-nvfp4-vllm.yaml \
  --hosts \
  localhost \
  --port \
  8001 \
  --tp \
  1 \
  --no-follow \
  -o \
  served_model_name=main \
  -o \
  network=proxy-tier \
  --executor-args \
  '-p 8001:8001' \
  --memory-limit \
  80G \
  -o \
  env.VLLM_ATTENTION_BACKEND=FLASHINFER \
  -o \
  env.VLLM_FLASHINFER_MOE_BACKEND=latency \
  -o \
  env.VLLM_BLACKWELL_LAYOUT=1 \
  -o \
  env.VLLM_BLACKWELL_UMA_OVERLAP=1 \
  -o \
  env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8=1 \
  -o \
  env.VLLM_USE_DEEP_GEMM=0 \
  -o \
  env.VLLM_OTEL_TRACING_ENABLED=1 \
  -o \
  env.OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 \
  -o \
  env.OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
  -o \
  env.OTEL_SERVICE_NAME=vllm-main \
  -o \
  host=0.0.0.0 \
  --tp \
  1 \
  --gpu-mem \
  0.81 \
  --max-model-len \
  262144 \
  -o \
  max_num_seqs=256 \
  -o \
  port=8001 \
  --container-name \
  main \
  --label \
  sparkrun.role=main \
  --label \
  sparkrun.monitoring=true
uv \
  run \
  sparkrun \
  run \
  /home/jlapenna/services/registry/models/bge-m3.yaml \
  --hosts \
  localhost \
  --port \
  8002 \
  --tp \
  1 \
  --no-follow \
  -o \
  served_model_name=embedding \
  -o \
  network=proxy-tier \
  --executor-args \
  '-p 8002:8002' \
  --memory-limit \
  4G \
  -o \
  env.VLLM_ATTENTION_BACKEND=FLASHINFER \
  -o \
  env.VLLM_FLASHINFER_MOE_BACKEND=latency \
  -o \
  env.VLLM_BLACKWELL_LAYOUT=1 \
  -o \
  env.VLLM_BLACKWELL_UMA_OVERLAP=1 \
  -o \
  env.VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8=1 \
  -o \
  env.VLLM_USE_DEEP_GEMM=0 \
  -o \
  env.VLLM_OTEL_TRACING_ENABLED=1 \
  -o \
  env.OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 \
  -o \
  env.OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
  -o \
  env.OTEL_SERVICE_NAME=vllm-embedding \
  -o \
  host=0.0.0.0 \
  --tp \
  1 \
  --gpu-mem \
  0.05 \
  --max-model-len \
  8192 \
  -o \
  max_num_batched_tokens=8192 \
  -o \
  port=8002 \
  --container-name \
  embedding \
  --label \
  sparkrun.role=embedding \
  --label \
  sparkrun.monitoring=true

echo "📦 Starting gateway and monitoring via docker compose..."
cd "$CDIR"
docker compose --env-file "$PARENT_ENV" up -d 2>/dev/null || docker compose up -d
echo "✅ Stack is operational."