# Dedicated Worker Deployment Guide (Mode B)
## Scaling the Platform on VPS / Cloud Servers with Celery & Redis

> [!NOTE]
> **When to use Mode B**: Mode B is recommended when your collection scale expands beyond 50,000 items/month, when you need real-time streaming Telegram MTProto listeners (`client.on(events.NewMessage)`), or when running headless browser rendering (Playwright/Scrapy).

---

### Architecture Overview (Mode B)
In Mode B, the web dashboard and REST API run on your primary server (or cPanel), while an optional external Linux VPS handles high-throughput asynchronous workers:

```
[ Central Database (MySQL / PostgreSQL) ]
        ▲                         ▲
        │                         │
[ Web Dashboard / API ]     [ Celery Worker Pool (VPS) ]
(Passenger or Gunicorn)              ▲
                                     │
                             [ Redis Broker ]
```

---

### Step 1: System Requirements & VPS Packages (Ubuntu 22.04 LTS)
```bash
sudo apt update && sudo apt install -y python3-pip python3-venv redis-server git supervisor
```

---

### Step 2: Configure Environment (.env) for Mode B
Set `EXECUTION_MODE=celery_worker` in `.env`:
```ini
EXECUTION_MODE=celery_worker
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
```

---

### Step 3: Supervisor Configuration for Continuous Workers
Create `/etc/supervisor/conf.d/market_intel_worker.conf`:
```ini
[program:market_intel_celery]
command=/home/deploy/market_intel/venv/bin/celery -A market_intel worker -l INFO --concurrency=4
directory=/home/deploy/market_intel
user=deploy
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/market_intel_worker.log

[program:market_intel_beat]
command=/home/deploy/market_intel/venv/bin/celery -A market_intel beat -l INFO
directory=/home/deploy/market_intel
user=deploy
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/market_intel_beat.log
```

Reload Supervisor:
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status
```
