import re

with open('d:\\bootstrap-5.3.8\\dist\\product\\index.html', 'r', encoding='utf-8') as f:
    content = f.read()

old_pattern = r'''                // Добавляем сообщение в DOM сразу со статусом "sending"
                var tempId = 'temp_' \+ Date\.now\(\);
                addMessageToDOM\(\{
                    id: tempId,
                    sender: currentUser\.username,
                    content: selectedFile \? selectedFile\.name : content,
                    created_at: new Date\(\)\.toLocaleTimeString\('ru-RU', \{hour: '2-digit', minute:'2-digit'\}\),
                    is_mine: true,
                    file_type: fileType,
                    status: 'sending'
                \}\);

                console\.log\('Отправка файла .+?а сервер\.\.\.', \{'''

new_text = '''                console.log('Отправка файла на сервер...', {'''

content = re.sub(old_pattern, new_text, content, flags=re.DOTALL)

with open('d:\\bootstrap-5.3.8\\dist\\product\\index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('Готово!')
