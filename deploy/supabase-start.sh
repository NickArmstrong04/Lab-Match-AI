#!/bin/sh
# Supabase recreates its network on every start, publishing on 0.0.0.0.
# Pre-create it bound to loopback so the DB never reaches the LAN.
set -e
cd "$HOME/Lab-Match-AI"
docker network create \
  -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 \
  --label com.supabase.cli.project=Lab-Match-AI \
  --label com.docker.compose.project=Lab-Match-AI \
  supabase_network_Lab-Match-AI 2>/dev/null || true
exec supabase start
