#!/usr/bin/env bash
# Rebuild RevEase images from ./src and push them to the host's private
# registry (registry:2 on localhost:5000, htpasswd-protected).
#
#   ./build.sh              # all three images, tag v1 (+ latest)
#   ./build.sh web          # just the web image
#   ./build.sh all v2       # everything as v2
#
# NEXT_PUBLIC_API_BASE is baked into the web image, so a change to WEB_API_BASE
# in .env means rebuilding web here — a restart alone will not pick it up.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a

SERVICE="${1:-all}"
TAG="${2:-${TAG:-v1}}"

python3 src/shift.py \
  --service "$SERVICE" \
  --tag "$TAG" \
  --repo "${REGISTRY:-localhost:5000/revease}" \
  --api-base "${WEB_API_BASE:-http://13.204.129.141:8020}"
