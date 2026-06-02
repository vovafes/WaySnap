# WaySnap

Open-source аналог ShareX для Linux. Скриншоты + продвинутые аннотации.

## Системные зависимости

| Среда      | Утилита | Установка                  |
|------------|---------|----------------------------|
| Wayland    | `grim`  | `sudo apt install grim`    |
| X11        | `maim`  | `sudo apt install maim`    |

## Установка и запуск

```bash
# 1. Клонировать
git clone https://github.com/vovafes/WaySnap.git && cd WaySnap

# 2. Виртуальное окружение
python3 -m venv .venv && source .venv/bin/activate

# 3. Python-зависимости
pip install -r requirements.txt

# 4. Запуск
python main.py
```

## Структура проекта

```
WaySnap/
├── main.py              # Точка входа: инициализация QApplication
└── waysnap/
    ├── tray.py          # TrayIconManager — иконка трея, меню, запуск захвата
    └── canvas.py        # AnnotationCanvas — полноэкранное окно с фоном-скриншотом
```

## Использование

- Приложение запускается в системный трей.
- **ЛКМ** по иконке или пункт меню **«Сделать скриншот»** — захват всего экрана.
- Открывается полноэкранное окно со «застывшим» экраном.
- **Escape** — закрыть окно аннотаций.
