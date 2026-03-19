# Celery конфигурация для фоновых задач
# Запуск: celery -A celery_worker worker --loglevel=info

import os
from celery import Celery
from kombu import Exchange, Queue

# Настройка Redis как брокера
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

app = Celery('jetesk', broker=REDIS_URL, backend=REDIS_URL)

# Конфигурация
app.conf.update(
    # Сериализация
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    
    # Таймауты
    task_ack_late_by=180,
    task_time_limit=300,
    task_soft_time_limit=240,
    
    # Retry
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Rate limiting
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    
    # Очереди
    task_queues=[
        Queue('default', Exchange('default'), routing_key='default'),
        Queue('files', Exchange('files'), routing_key='files'),
        Queue('notifications', Exchange('notifications'), routing_key='notifications'),
    ],
    task_default_queue='default',
    task_default_exchange='default',
    task_default_routing_key='default',
    
    # Расписание (для периодических задач)
    beat_schedule={
        'cleanup-old-messages': {
            'task': 'tasks.cleanup_old_messages',
            'schedule': 3600.0,  # Каждый час
        },
        'update-user-status': {
            'task': 'tasks.update_user_status',
            'schedule': 60.0,  # Каждую минуту
        },
    },
)


# Автообнаружение задач
app.autodiscover_tasks(['tasks'])


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
