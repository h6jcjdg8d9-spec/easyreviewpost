import os

workers = 2
worker_class = "sync"
timeout = 30
graceful_timeout = 20
keepalive = 5
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

# Log to stdout so Render captures everything
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Kill a stuck worker after 30s instead of hanging forever
worker_connections = 100
