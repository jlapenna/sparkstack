# Cloudflare Zero Trust Setup

This directory manages the **Cloudflare Tunnel** (`cloudflared`) used to securely expose internal AI and communication services to the internet without opening inbound firewall ports.

## Management

### Tunnel Management

The tunnel is managed natively by the stack's orchestration scripts (`uv run manager/update_services.py` and `manager/set_current.py`).

You can also manage it manually using native docker compose (ensure you pass the root `.env` file):

```bash
docker compose --env-file ../../.env up -d    # Start the tunnel
docker compose --env-file ../../.env logs -f  # View logs
docker compose --env-file ../../.env ps       # Check status
```

### Adding a New Service (e.g. Matrix)

1. **Join the Network:** Add this to the new service's `docker-compose.yml`:
   ```yaml
   networks:
     spark-stack-net:
       external: true
   ```
1. **Map in Dashboard:**
   - Go to **Networks > Connectors** in Cloudflare.
   - Add a Public Hostname: `matrix-spark.joelapenna.com` -> `http://container_name:8008`.

### Common Commands

```bash
# View tunnel status and connection logs
docker compose logs -f tunnel

# Restart the tunnel connector
docker compose restart tunnel

# Connect an existing container manually to the proxy
docker network connect spark-stack-net <container_name>
```

## Files

- `docker-compose.yml`: Defines the `cloudflared` connector.
- `.env`: Contains the `TUNNEL_TOKEN` (Do not commit to git).
