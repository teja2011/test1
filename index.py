# Vercel Serverless Function entry point
import sys
import os

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(__file__))

from messenger_server import app
