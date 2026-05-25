import os
from pathlib import Path
from datetime import datetime


def collect_project_for_ai(project_dir: str | Path = ".", output_file: str = "project_for_ai.txt"):
    """
    Собирает все важные файлы проекта в один .txt файл для загрузки в AI.
    В НАЧАЛЕ ФАЙЛА добавляет структуру проекта (дерево папок).
    """

    project_dir = Path(project_dir).resolve()
    output_path = Path(output_file)

    # Папки для исключения
    exclude_dirs = {
        '.venv', 'venv', '__pycache__', 'logs',
        '.git', '.idea', '.pytest_cache', '.mypy_cache',
        'backups', 'uploads', 'Scratches and Consoles',
        'External Libraries'
    }

    # Файлы для исключения
    exclude_files = {'__init__.py'}

    collected_files = []
    total_lines = 0

    print(f"🔍 Сканирую проект: {project_dir}")
    print("-" * 60)

    # Сначала собираем структуру проекта
    project_structure = []

    for root, dirs, files in os.walk(project_dir):
        # Фильтруем папки
        dirs[:] = sorted([d for d in dirs if d not in exclude_dirs and not d.startswith('.')])

        # Пропускаем папки data/backups и data/uploads
        if 'backups' in str(root) or 'uploads' in str(root):
            continue

        # Вычисляем уровень вложенности
        rel_root = Path(root).relative_to(project_dir)
        level = rel_root.as_posix().count('/')

        # Добавляем папку в структуру
        if level == 0:
            project_structure.append(f"📁 {project_dir.name}/")
        else:
            indent = "│   " * (level - 1) + "├── "
            project_structure.append(f"{indent}📁 {rel_root.name}/")

        # Добавляем файлы в структуру
        for file in sorted(files):
            if file in exclude_files:
                continue
            if '.venv' in str(root) or 'venv' in str(root):
                continue

            # Показываем только нужные файлы в структуре
            if (file.endswith('.py') or
                    file in ['.env', '.gitignore', 'requirements.txt', 'config.py'] or
                    file.endswith(('.txt', '.json', '.yaml', '.yml', '.md'))):
                indent = "│   " * level + "├── "
                project_structure.append(f"{indent}📄 {file}")

    # Теперь собираем содержимое файлов
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]

        if 'backups' in str(root) or 'uploads' in str(root):
            continue

        for file in sorted(files):
            filepath = Path(root) / file

            if file in exclude_files:
                continue
            if '.venv' in str(filepath) or 'venv' in str(filepath):
                continue

            if (file.endswith('.py') or
                    file in ['.env', '.gitignore', 'requirements.txt', 'config.py'] or
                    file.endswith(('.txt', '.json', '.yaml', '.yml', '.md'))):

                if filepath.resolve() == output_path.resolve():
                    continue

                try:
                    content = filepath.read_text(encoding='utf-8')
                    rel_path = filepath.relative_to(project_dir)

                    collected_files.append({
                        'path': str(rel_path),
                        'content': content,
                        'lines': len(content.splitlines())
                    })
                    total_lines += len(content.splitlines())

                    print(f"✅ {rel_path} ({len(content.splitlines())} строк)")

                except Exception as e:
                    print(f"❌ Ошибка чтения {filepath}: {e}")

    # Создаем итоговый файл
    with open(output_path, 'w', encoding='utf-8') as f:
        # Заголовок
        f.write("=" * 80 + "\n")
        f.write("📦 PROJECT DUMP FOR AI ASSISTANT\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Project: {project_dir.name}\n")
        f.write(f"Total files: {len(collected_files)}\n")
        f.write(f"Total lines: {total_lines}\n")
        f.write("=" * 80 + "\n\n")

        # СТРУКТУРА ПРОЕКТА
        f.write("📁 PROJECT STRUCTURE:\n")
        f.write("-" * 60 + "\n")
        for line in project_structure:
            f.write(line + "\n")
        f.write("-" * 60 + "\n\n")

        # Содержание файлов
        for file_info in collected_files:
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"📄 FILE: {file_info['path']}\n")
            f.write(f"📏 LINES: {file_info['lines']}\n")
            f.write("=" * 80 + "\n\n")
            f.write(file_info['content'])
            f.write("\n\n")

    print("-" * 60)
    print(f"✅ ГОТОВО! Собрано {len(collected_files)} файлов, {total_lines} строк")
    print(f"📁 Файл сохранен: {output_path.absolute()}")
    print("=" * 60)


# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    #  Если скрипт лежит ВНУТРИ проекта prpp → используйте точку
    PROJECT_PATH = "."

    # 🔴 Если скрипт лежит ВНЕ проекта → укажите полный путь
    # PROJECT_PATH = r"D:\_pythone\prpp"

    collect_project_for_ai(
        project_dir=PROJECT_PATH,
        output_file="project_for_ai.txt"
