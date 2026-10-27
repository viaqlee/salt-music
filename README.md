# Salt Music

Загрузчик музыки с YouTube / YouTube Music для Linux: треки, альбомы, EP, синглы и целые страницы исполнителей, с тегами, обложками, жанрами, плеером и отправкой на телефон через adb.

## Зависимости системы

```
sudo pacman -S ffmpeg mpv deno android-tools zenity
```

- **ffmpeg** — извлечение звука и конвертация в MP3/FLAC
- **mpv** — встроенный плеер
- **deno** — нужен yt-dlp для расшифровки подписей YouTube
- **android-tools** (adb) — отправка на телефон, необязательно
- **zenity** — диалог выбора папки

## Установка

Одним файлом: соберите установщик и запустите его (двойным кликом или из терминала):

```
installer/build.sh
./dist/SaltMusic-Setup-0.1.run
```

Мастер установит программу в `~/.local/share/salt-music/app`, проверит системные пакеты (и предложит
поставить недостающие через pacman), создаст ярлык в меню и команду `salt-music`. Удаление — пункт
меню «Uninstall Salt Music» или `SaltMusic-Setup-0.1.run --uninstall`. Без вопросов: `--unattended`.

Вручную, для разработки:

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Запуск

```
./salt-music.sh
```

## Если YouTube пишет «подтвердите, что вы не бот»

Справа в «Источнике» выберите браузер, где вы залогинены в YouTube, — cookies будут браться оттуда.

## Где что хранится

- настройки: `~/.config/salt-music/settings.json`
- архив загрузок, история, жанры исполнителей: `~/.local/share/salt-music/`
