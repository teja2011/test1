# Vercel Serverless Function entry point
import os
import sys

# Добавляем родительскую директорию в path для импорта messenger_server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from messenger_server import app
