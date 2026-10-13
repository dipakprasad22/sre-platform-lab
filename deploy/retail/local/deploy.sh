#!/usr/bin/env bash
# Deploy (or update) all retail services with Helm.
# Usage: deploy/retail/local/deploy.sh            -> uses image tag "dev"
#        TAG=abc1234 deploy/retail/local/deploy.sh -> uses image tag "abc1234"
#
# --rollback-on-failure: if a service does not become healthy in time,
#   Helm puts back the previous working version automatically.
# --force-conflicts: Helm is the only owner of these objects, so it wins
#   any field-ownership conflict (for example after a manual kubectl change).
set -euo pipefail

CHART=platform/charts/service
VALUES=deploy/retail/local
TAG="${TAG:-dev}"

for svc in catalog cart payment-mock orders; do
  echo "==> $svc (tag $TAG)"
  helm upgrade --install "$svc" "$CHART" \
    --namespace retail \
    --values "$VALUES/$svc.yaml" \
    --set-string image.tag="$TAG" \
    --rollback-on-failure \
    --force-conflicts \
    --timeout 5m
done

helm list -n retail
