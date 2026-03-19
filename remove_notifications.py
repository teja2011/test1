# -*- coding: utf-8 -*-

# Читаем файл
with open(r'd:\bootstrap-5.3.8\dist\product\index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Находим строки с функциями уведомлений (примерно строки 2314-2431)
# И удаляем их

# Строки для удаления (0-based индекс, поэтому -1)
# От строки 2314 (// === Уведомления ===) до строки 2431 (конец markAllAsRead)
start_line = 2313  # 2314 - 1 (0-based)
end_line = 2431    # 2431 + 1 (чтобы включить пустую строку после)

# Проверяем, что нашли правильные строки
print(f"Строка {start_line + 1}: {repr(lines[start_line][:50])}")
print(f"Строка {end_line}: {repr(lines[end_line][:50])}")

# Удаляем строки
new_lines = lines[:start_line] + lines[end_line:]

# Сохраняем файл
with open(r'd:\bootstrap-5.3.8\dist\product\index.html', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Удалено строк: {end_line - start_line}")
print("Готово!")
