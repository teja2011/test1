"""
Конвертация логотипа Jetesk.png в base64 и встраивание в index.html
"""
import base64
import os
import re

# Пути
CURRENT_DIR = os.path.dirname(__file__)
LOGO_PATH = os.path.join(CURRENT_DIR, 'Jetesk.png')
HTML_PATH = os.path.join(CURRENT_DIR, 'index.html')

# Читаем логотип
with open(LOGO_PATH, 'rb') as f:
    logo_data = f.read()
    logo_base64 = base64.b64encode(logo_data).decode('utf-8')
    logo_data_uri = f'data:image/png;base64,{logo_base64}'

print(f"Logo read: {len(logo_data)} bytes")
print(f"Base64 length: {len(logo_base64)} chars")

# Читаем HTML
with open(HTML_PATH, 'r', encoding='utf-8') as f:
    html_content = f.read()

# Заменяем все ссылки на Jetesk.png на base64
html_content = html_content.replace('href="Jetesk.png"', f'href="{logo_data_uri}"')
html_content = html_content.replace('src="Jetesk.png"', f'src="{logo_data_uri}"')

# Сохраняем HTML
with open(HTML_PATH, 'w', encoding='utf-8') as f:
    f.write(html_content)

print("index.html updated")
print("Logo embedded successfully!")
