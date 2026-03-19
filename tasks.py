# Фоновые задачи Celery
import os
import sys
import time
from datetime import datetime, timedelta

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(__file__))

from celery_worker import app
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Настройка БД
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
else:
    engine = create_engine('sqlite:///messenger.db', echo=False, connect_args={'check_same_thread': False})


@app.task(bind=True, max_retries=3, queue='files')
def send_file_task(self, sender_id, recipient_id, file_data, file_type):
    """
    Фоновая отправка файла (изображения/видео)
    Используется для тяжелых файлов чтобы не блокировать HTTP запрос
    """
    try:
        db = sessionmaker(bind=engine)()
        
        # Импортируем модели
        from messenger_server import Message, create_notification, User
        
        # Создаем сообщение
        msg = Message(
            sender_id=sender_id,
            recipient_id=recipient_id if recipient_id else None,
            content=file_data,
            file_type=file_type,
            status='sending'  # Статус "отправляется"
        )
        db.add(msg)
        db.commit()
        
        # Обновляем статус на "sent"
        msg.status = 'sent'
        db.commit()
        
        # Создаем уведомление
        if recipient_id:
            recipient = db.query(User).filter_by(id=recipient_id).first()
            if recipient:
                create_notification(
                    db=db,
                    user_id=recipient_id,
                    message=f"Новый файл от пользователя {sender_id}",
                    sender_id=sender_id,
                    notif_type='file'
                )
        
        db.close()
        
        return {
            'success': True,
            'message_id': msg.id,
            'status': 'sent'
        }
        
    except Exception as e:
        # Retry с экспоненциальной задержкой
        raise self.retry(exc=e, countdown=2 ** self.request.retries)


@app.task(bind=True, max_retries=3, queue='notifications')
def send_notification_task(self, user_id, message, sender_id=None, notif_type='message'):
    """
    Фоновая отправка уведомления
    """
    try:
        db = sessionmaker(bind=engine)()
        from messenger_server import Notification, create_notification
        
        notification = create_notification(
            db=db,
            user_id=user_id,
            message=message,
            sender_id=sender_id,
            notif_type=notif_type
        )
        
        db.close()
        
        return {
            'success': True,
            'notification_id': notification.id if notification else None
        }
        
    except Exception as e:
        raise self.retry(exc=e, countdown=2 ** self.request.retries)


@app.task(queue='default')
def cleanup_old_messages():
    """
    Очистка старых сообщений (старше 30 дней)
    Запускается по расписанию каждый час
    """
    try:
        db = sessionmaker(bind=engine)()
        from messenger_server import Message
        
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        
        # Удаляем старые сообщения
        deleted = db.query(Message).filter(
            Message.created_at < cutoff_date
        ).delete(synchronize_session=False)
        
        db.commit()
        db.close()
        
        print(f"[Cleanup] Deleted {deleted} old messages")
        return {'deleted': deleted}
        
    except Exception as e:
        print(f"[Cleanup] Error: {e}")
        return {'error': str(e)}


@app.task(queue='default')
def update_user_status():
    """
    Обновление статуса пользователей (онлайн/офлайн)
    Запускается каждую минуту
    """
    try:
        db = sessionmaker(bind=engine)()
        from messenger_server import User
        
        # Считаем офлайн пользователей которые не были в сети больше 10 минут
        offline_threshold = datetime.utcnow() - timedelta(minutes=10)
        
        # Здесь можно добавить дополнительную логику
        # Например, отправку push-уведомлений
        
        db.close()
        
        return {'status': 'ok'}
        
    except Exception as e:
        print(f"[UserStatus] Error: {e}")
        return {'error': str(e)}


@app.task(bind=True, queue='files')
def process_large_file(self, file_path, sender_id, recipient_id):
    """
    Обработка больших файлов (сжатие, оптимизация)
    """
    try:
        import cloudinary
        import cloudinary.uploader
        
        if os.environ.get('CLOUDINARY_CLOUD_NAME'):
            # Загрузка в Cloudinary
            result = cloudinary.uploader.upload(
                file_path,
                folder='jetesk_uploads',
                resource_type='auto'
            )
            
            # Удаляем локальный файл
            os.remove(file_path)
            
            return {
                'success': True,
                'url': result['secure_url'],
                'public_id': result['public_id']
            }
        else:
            # Возвращаем локальный путь
            return {
                'success': True,
                'local_path': file_path
            }
            
    except Exception as e:
        print(f"[ProcessFile] Error: {e}")
        return {'error': str(e)}
