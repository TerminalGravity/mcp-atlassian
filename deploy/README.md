# Jira Knowledge - Production Deployment

Deploy the Jira Knowledge web app (FastAPI + Next.js + MongoDB + LanceDB) to a VPS with HTTPS and basic auth.

## Architecture

```
Internet -> Caddy (HTTPS + basic auth) -> Docker network
                |- :443/          -> frontend:3000  (Next.js)
                |- :443/api/*     -> backend:8000   (FastAPI)
                \- auto-TLS via Let's Encrypt

Docker containers: caddy, backend, frontend, mongodb
Volumes: mongodb_data, lancedb_data, caddy_data
```

## Prerequisites

- VPS with Ubuntu 22.04+ (2GB+ RAM recommended)
- Docker and Docker Compose installed
- A domain name pointed to the VPS IP

## Setup

### 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in
```

### 2. Clone and configure

```bash
git clone <repo-url> mcp-atlassian
cd mcp-atlassian/deploy
cp .env.example .env
```

### 3. Fill in secrets

Edit `.env` with your actual values:

```bash
# Generate the basic auth password hash
docker run caddy caddy hash-password --plaintext "your-secure-password"
# Copy the output into AUTH_HASH in .env
```

Required variables:
- `DOMAIN` - Your domain (e.g., `jira.example.com`)
- `AUTH_USER` / `AUTH_HASH` - Basic auth credentials
- `JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN` - Jira connection
- `OPENAI_API_KEY` - For embeddings and chat

### 4. Point DNS

Create an A record: `jira.yourdomain.com` -> `<VPS-IP>`

Wait for DNS propagation (check with `dig jira.yourdomain.com`).

### 5. Deploy

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

First startup takes a few minutes:
1. Backend builds and starts
2. Initial vector sync runs (can take 5-10 min for large projects)
3. Frontend builds the Next.js production bundle
4. Caddy provisions TLS certificate automatically

### 6. Verify

```bash
# Check all containers are running
docker compose -f docker-compose.prod.yml ps

# Check logs
docker compose -f docker-compose.prod.yml logs -f backend

# Test health endpoint (with auth)
curl -u adr:yourpassword https://jira.yourdomain.com/api/health
```

Visit `https://jira.yourdomain.com` - you'll get a basic auth prompt, then the app.

## Operations

### View logs

```bash
docker compose -f docker-compose.prod.yml logs -f [service]
```

### Restart a service

```bash
docker compose -f docker-compose.prod.yml restart backend
```

### Update deployment

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

### Trigger manual sync

```bash
curl -u adr:yourpassword -X POST https://jira.yourdomain.com/api/sync/trigger
```

Or use the Settings page in the UI.

## Resource Requirements

| Service  | Memory Limit | Notes                          |
|----------|-------------|--------------------------------|
| Backend  | 2GB         | Embeddings + sync              |
| Frontend | 512MB       | Next.js standalone             |
| MongoDB  | 512MB       | Settings + chat history        |
| Caddy    | -           | Minimal (reverse proxy + TLS)  |

Minimum VPS: 4GB RAM recommended.

## Troubleshooting

### Caddy can't get TLS certificate
- Ensure DNS A record points to VPS IP
- Ensure ports 80 and 443 are open (no firewall blocking)
- Check Caddy logs: `docker compose -f docker-compose.prod.yml logs caddy`

### Backend health check failing
- The backend has a 120s start period for initial sync
- Check backend logs for Jira connection errors
- Verify JIRA_API_TOKEN is valid

### Vector search returns no results
- Wait for initial sync to complete (check Settings > Sync page)
- Or trigger manually: `curl -u user:pass -X POST https://domain/api/sync/trigger`
