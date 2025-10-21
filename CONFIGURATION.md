# Whombat Configuration Guide

This guide explains how to configure Whombat for different deployment scenarios.

## Quick Start

1. **Copy the environment template:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` and set your domain:**
   ```bash
   # For remote server access
   WHOMBAT_DOMAIN=your-server-ip-or-domain

   # For local development only
   WHOMBAT_DOMAIN=localhost
   ```

3. **Start Whombat:**
   ```bash
   ./scripts/start.sh
   ```

That's it! All other configurations (CORS, frontend URL, etc.) are automatically generated.

## Configuration Files

### Root `.env` (Single Source of Truth)

This is the **only** file you need to edit. All configurations are derived from this file.

- **Location:** `/path/to/whombat/.env`
- **Auto-generated:** `front/.env` (generated automatically by `start.sh`)

### Key Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `WHOMBAT_DOMAIN` | Domain or IP where Whombat is accessed | `localhost` | ✅ Yes |
| `WHOMBAT_HOST` | Network interface to bind (use `0.0.0.0` for remote) | `0.0.0.0` | No |
| `WHOMBAT_PORT` | Backend server port | `5000` | No |
| `WHOMBAT_FRONTEND_PORT` | Frontend server port | `3000` | No |
| `WHOMBAT_PROTOCOL` | Protocol (`http` or `https`) | `http` | No |
| `WHOMBAT_DEV` | Development mode (`true` or `false`) | `false` | No |

## Deployment Scenarios

### 1. Local Development

Perfect for development on your laptop/desktop.

```bash
# .env
WHOMBAT_DOMAIN=localhost
WHOMBAT_HOST=localhost
WHOMBAT_DEV=true
```

**Access:**
- Frontend: `http://localhost:3000`
- Backend: `http://localhost:5000`

### 2. Remote Server (IP Address)

For deployment on a remote server accessed by IP address.

```bash
# .env
WHOMBAT_DOMAIN=192.168.1.100
WHOMBAT_HOST=0.0.0.0
WHOMBAT_PORT=5000
WHOMBAT_FRONTEND_PORT=3000
WHOMBAT_PROTOCOL=http
```

**Access:**
- Frontend: `http://192.168.1.100:3000`
- Backend: `http://192.168.1.100:5000`

**Important:** Make sure firewall allows ports 3000 and 5000.

### 3. Remote Server (Domain Name)

For deployment with a custom domain.

```bash
# .env
WHOMBAT_DOMAIN=whombat.example.com
WHOMBAT_HOST=0.0.0.0
WHOMBAT_PROTOCOL=http
```

**Access:**
- Frontend: `http://whombat.example.com:3000`
- Backend: `http://whombat.example.com:5000`

### 4. Production with HTTPS

For secure production deployment with SSL certificates.

```bash
# .env
WHOMBAT_DOMAIN=whombat.example.com
WHOMBAT_HOST=0.0.0.0
WHOMBAT_PROTOCOL=https
WHOMBAT_DEV=false
WHOMBAT_AUTH_COOKIE_SECURE=true
```

**Note:** You need to set up a reverse proxy (nginx, caddy) with SSL certificates.

## Automatic Configurations

The following are **automatically configured** based on your `.env` settings:

### 1. Frontend Environment (`front/.env`)

Generated automatically when you run `./scripts/start.sh`. Do not edit manually.

### 2. CORS Origins

Automatically generated from `WHOMBAT_DOMAIN` and `WHOMBAT_FRONTEND_PORT`:
- Always includes `http://localhost:3000` and `http://127.0.0.1:3000` for development
- Automatically adds your domain (e.g., `http://192.168.1.100:3000`)

**Manual override (advanced):**
```bash
# .env
WHOMBAT_CORS_ORIGINS='["http://localhost:3000","http://custom-domain.com:3000"]'
```

### 3. Authentication Cookies

Cookies automatically use `WHOMBAT_DOMAIN` for the domain setting.

## Troubleshooting

### Cannot access from remote machine

1. **Check `WHOMBAT_HOST`:**
   ```bash
   # Should be 0.0.0.0, not localhost
   WHOMBAT_HOST=0.0.0.0
   ```

2. **Check firewall:**
   ```bash
   sudo ufw allow 3000
   sudo ufw allow 5000
   ```

3. **Check `WHOMBAT_DOMAIN`:**
   ```bash
   # Should be your server's IP or domain, not localhost
   WHOMBAT_DOMAIN=192.168.1.100
   ```

### CORS errors in browser console

Usually auto-configured correctly. If you see CORS errors:

1. **Check frontend is using correct backend URL:**
   ```bash
   cat front/.env
   # Should show: NEXT_PUBLIC_BACKEND_HOST=http://your-domain:5000
   ```

2. **Restart both servers:**
   ```bash
   ./scripts/stop.sh
   ./scripts/start.sh
   ```

3. **Check CORS origins in backend logs:**
   Look for "CORS origins" in `logs/backend.log`

### Authentication/login issues

1. **Check cookie domain matches your access domain:**
   - If accessing via `http://192.168.1.100:3000`, domain should be `192.168.1.100`
   - If accessing via `http://localhost:3000`, domain should be `localhost`

2. **For HTTPS, ensure secure cookies:**
   ```bash
   WHOMBAT_AUTH_COOKIE_SECURE=true
   ```

## Migration from Previous Versions

If you previously had hardcoded configurations:

1. **Backup your current `.env` files:**
   ```bash
   cp .env .env.backup
   cp front/.env front/.env.backup
   ```

2. **Copy the new template:**
   ```bash
   cp .env.example .env
   ```

3. **Set your domain in `.env`:**
   ```bash
   # Edit .env and set:
   WHOMBAT_DOMAIN=your-server-ip
   ```

4. **Remove old hardcoded values:**
   - Delete `front/.env` (will be auto-generated)
   - Remove any hardcoded IPs from scripts

5. **Restart:**
   ```bash
   ./scripts/start.sh
   ```

## Advanced Configuration

### Custom Ports

```bash
# .env
WHOMBAT_PORT=8000
WHOMBAT_FRONTEND_PORT=8080
```

### Audio Directory

```bash
# .env
WHOMBAT_AUDIO_DIR=/path/to/audio/files
```

**Note:** You can also set this via the web UI on first run.

### Database Configuration

For PostgreSQL (instead of SQLite):

```bash
# .env
POSTGRES_DB=whombat
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
```

## Summary

**What you need to configure:**
- ✅ `WHOMBAT_DOMAIN` (your server IP or domain)
- ✅ `WHOMBAT_HOST` (`0.0.0.0` for remote access)

**What's automatically configured:**
- ✅ Frontend `.env` file
- ✅ CORS origins
- ✅ Backend URL for frontend
- ✅ Cookie domain
- ✅ All other network settings

**Result:**
- One simple configuration file (`.env`)
- No hardcoded values
- Easy to deploy anywhere
- Works out of the box
