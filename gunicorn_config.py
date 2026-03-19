# Gunicorn конфиг для асинхронного запуска с gevent
# Запуск: gunicorn -c gunicorn_config.py messenger_server:app

import multiprocessing
import os

# Количество воркеров (CPU * 2 + 1 для I/O задач)
workers = multiprocessing.cpu_count() * 2 + 1

# Используем gevent для асинхронности
worker_class = 'gevent'

# Каждый воркер обрабатывает до 1000 соединений
worker_connections = 1000

# Таймаут воркера (сек)
timeout = 120

# Keep-alive соединения
keepalive = 5

# Адрес и порт
bind = os.environ.get('BIND_ADDRESS', '0.0.0.0:8000')

# Логирование
accesslog = '-'  # stdout
errorlog = '-'   # stderr
loglevel = 'info'

# Предзагрузка приложений (экономия памяти)
preload_app = True

# Максимальное количество запросов до перезапуска воркера
max_requests = 1000
max_requests_jitter = 50

# Graceful timeout
graceful_timeout = 30

# Daemon mode (False для разработки)
daemon = False

# PID file
pidfile = '/tmp/gunicorn.pid' if os.name != 'nt' else None

# Hooks
def on_starting(server):
    print("[Gunicorn] Server starting...")

def on_reload(server):
    print("[Gunicorn] Server reloading...")

def worker_int(worker):
    """Получен сигнал SIGINT"""
    print(f"[Gunicorn] Worker {worker.pid} received SIGINT")

def worker_abort(worker):
    """Получен сигнал SIGABRT"""
    print(f"[Gunicorn] Worker {worker.pid} received SIGABRT")

def pre_fork(server, worker):
    """Перед форком воркера"""
    pass

def post_fork(server, worker):
    """После форка воркера"""
    print(f"[Gunicorn] Worker {worker.pid} started")

def post_worker_init(worker):
    """После инициализации воркера"""
    # Инициализация gevent
    from gevent import monkey
    monkey.patch_all()
    print(f"[Gunicorn] Worker {worker.pid} gevent patched")

def worker_exit(server, worker):
    """Воркер завершается"""
    print(f"[Gunicorn] Worker {worker.pid} exiting")

def on_exit(server):
    """Сервер завершается"""
    print("[Gunicorn] Server exiting")
