import re

# Read the file
with open(r'd:\bootstrap-5.3.8\dist\product\index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Define the old pattern (from "// Переключение между вкладками чатов и настроек" to end of showSettingsTab function)
old_pattern = r'// Переключение между вкладками чатов и настроек\s*function initTabs\(\).*?function showSettingsTab\(\).*?renderSettingsContent\(\);.*?\}'

# Define the new code
new_code = '''// Открытие/закрытие модального окна настроек
        function openSettingsModal() {
            var modal = document.getElementById('settingsModal');
            if (modal) {
                modal.classList.add('show');
                renderSettingsContent();
                log('Settings modal opened');
            }
        }

        function closeSettingsModal() {
            var modal = document.getElementById('settingsModal');
            if (modal) {
                modal.classList.remove('show');
                log('Settings modal closed');
            }
        }'''

# Replace
new_content = re.sub(old_pattern, new_code, content, flags=re.DOTALL)

# Write back
with open(r'd:\bootstrap-5.3.8\dist\product\index.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Replacement completed successfully!")
