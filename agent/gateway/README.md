# Agent Gateway

Run this on the machine hosting the local Qwen3.5-9B service. The model endpoint
is loopback-only; the gateway is the shared bridge for remote consumers.

```bash
export POLYDATA_AGENT_GATEWAY_TOKEN="<shared-secret>"
export POLYDATA_AGENT_ENABLED=true
export POLYDATA_AGENT_API_BASE=http://127.0.0.1:18003/v1
export POLYDATA_AGENT_MODEL=qwen3.5-9b
export POLYDATA_AGENT_API_KEY=EMPTY
export POLYDATA_AGENT_RUNTIME=chat
python -m agent.gateway.app
```

For a remote API host, reuse its existing reverse SSH tunnel (do not create a
second listener if one is already installed):

```bash
ssh -N -R 127.0.0.1:18700:127.0.0.1:18700 "${POLYDATA_AGENT_GATEWAY_REMOTE}"
```

On the API/seed host, configure the gateway address reachable from that host:

```bash
POLYDATA_AGENT_GATEWAY_BASE_URL=http://127.0.0.1:18700
POLYDATA_AGENT_GATEWAY_URL=http://127.0.0.1:18700/agent/market-insights
POLYDATA_AGENT_GATEWAY_TOKEN=<shared-secret>
```

If the gateway or tunnel is unavailable, the GCP API falls back to its local deterministic/search fallback.
