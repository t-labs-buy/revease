#!/usr/bin/env bash
# Rebuild RevEase images from ./src and push them to the host's private
# registry (registry:2 on localhost:5000, htpasswd-protected).
#
#   ./build.sh              # all three images, tag v1 (+ latest)
#   ./build.sh web          # just the web image
#   ./build.sh all v2       # everything as v2
#
# Every image gets two names: the registry one it is pushed under, and the short
# IMAGE_NS one the compose file runs (so `docker ps` stays readable). They point at
# the same image id.
#
# NEXT_PUBLIC_API_BASE is baked into the web image, so a change to WEB_API_BASE
# in .env means rebuilding web here — a restart alone will not pick it up.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a

SERVICE="${1:-all}"
TAG="${2:-${TAG:-v1}}"

REPO="${REGISTRY:-localhost:5000/revease}"
NS="${IMAGE_NS:-revease}"

python3 src/shift.py \
  --service "$SERVICE" \
  --tag "$TAG" \
  --repo "$REPO" \
  --api-base "${WEB_API_BASE:-http://13.204.129.141:8020/api}"

if [ "$SERVICE" = "all" ]; then SERVICES="api worker web"; else SERVICES="$SERVICE"; fi
for svc in $SERVICES; do
    for t in "$TAG" latest; do
        docker tag "$REPO:$svc-$t" "$NS:$svc-$t"
        echo "tagged $NS:$svc-$t"
    done
done
