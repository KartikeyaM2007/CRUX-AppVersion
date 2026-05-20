# Crux Domain Deployment Guide

Use this when you want to host Crux on your personal domain.

## Recommended Production Shape

Crux is a Python FastAPI app. For a personal domain, host it on a VPS or app platform that supports long-running Python processes.

Good options:

- VPS: DigitalOcean, Hetzner, AWS Lightsail, Azure VM
- App platforms: Render, Railway, Fly.io

If you need Ollama/Llama 3 on the same server, use a VPS with enough RAM/CPU/GPU for the model. If you only want the UI and pandas/CTGAN flow, a normal Python app host is enough.

## Basic VPS Steps

1. Point your domain DNS:

   ```text
   A record: yourdomain.com -> your server public IP
   CNAME: www -> yourdomain.com
   ```

2. Copy the `web/` folder to the server.

3. Create a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Run the app with Uvicorn:

   ```bash
   uvicorn app:app --host 127.0.0.1 --port 8000
   ```

5. Put Nginx in front of it:

   ```nginx
   server {
       server_name yourdomain.com www.yourdomain.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

6. Add HTTPS:

   ```bash
   sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
   ```

7. Run Crux as a service with systemd:

   ```ini
   [Unit]
   Description=Crux FastAPI App
   After=network.target

   [Service]
   WorkingDirectory=/path/to/synthetic_data_engine/web
   ExecStart=/path/to/synthetic_data_engine/web/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
   Restart=always
   User=YOUR_SERVER_USER

   [Install]
   WantedBy=multi-user.target
   ```

## Ollama Note

If you want repair to use local Llama 3 on the server:

```bash
ollama pull llama3
ollama serve
```

Make sure Ollama is reachable only locally unless you intentionally secure it behind authentication.

## Production Caution

Crux currently runs tasks synchronously. For public hosting, add:

- Authentication
- Upload size limits
- Background jobs for long generation runs
- Per-user workspaces
- Cleanup of old CSV outputs
- Server-side rate limits
