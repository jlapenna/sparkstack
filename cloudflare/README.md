# Cloudflare Zero Trust Setup

This directory manages the **Cloudflare Tunnel** (`cloudflared`) used to securely expose internal AI and communication services to the internet without opening inbound firewall ports.

## Management

### Tunnel Helper

Use the `./tunnel.sh` script to manage the tunnel. It automatically loads secrets from the parent `.env` file:

```bash
./tunnel.sh up -d    # Start the tunnel
./tunnel.sh logs -f  # View logs
./tunnel.sh ps       # Check status
```

### Adding a New Service (e.g. Matrix)

1. **Join the Network:** Add this to the new service's `docker-compose.yml`:
   ```yaml
   networks:
     proxy-tier:
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
docker network connect proxy-tier <container_name>
```

## Files

- `docker-compose.yml`: Defines the `cloudflared` connector.
- `.env`: Contains the `TUNNEL_TOKEN` (Do not commit to git).
