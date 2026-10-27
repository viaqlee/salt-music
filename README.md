# Salt Music

Загрузчик музыки с YouTube / YouTube Music для Windows и Linux. Скачивает треки,
альбомы, EP, синглы и целые страницы исполнителей с тегами, обложками и жанрами.
Есть плеер и отправка на телефон через adb.

Код один для обеих систем. Всё, что зависит от системы, лежит в
`salt_music/desktop/`, `paths.py`, `proc.py` и `tools.py`.

Нужные программы:

- **ffmpeg** — извлечение звука и конвертация;
- **deno** — нужен yt-dlp для расшифровки подписей YouTube;
- **mpv** — встроенный плеер;
- **adb** — отправка на телефон, необязательно.

## Windows

### Установка

Скачайте `SaltMusic-Setup-<версия>.exe` из [релизов](../../releases) и запустите.
Права администратора не нужны, программа ставится в `%LOCALAPPDATA%\Programs\SaltMusic`.
Установщик предложит поставить через winget то, чего нет на компьютере:

| Программа | winget |
|---|---|
| FFmpeg | `Gyan.FFmpeg` |
| Deno | `DenoLand.Deno` |
| Android Platform Tools (adb) | `Google.PlatformTools` |
| mpv | `shinchiro.mpv` |

Есть и вариант без установки: `SaltMusic-<версия>-portable.zip`. Программу, поставленную
позже, Salt Music найдёт сама примерно за 10 секунд, перезапуск не нужен.

### Из исходников

Нужен Python 3.11+.

```bat
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run.bat
```

### Сборка установщика

Нужны Python и [Inno Setup 6](https://jrsoftware.org/isinfo.php).

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
# ffmpeg, deno, adb и mpv внутрь пакета, с проверкой sha256 там, где она опубликована:
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -BundleTools
```

Релизы собирает GitHub Actions (`.github/workflows/release-windows.yml`) по тегу `v<версия>`.

## Linux

### Зависимости системы

```
sudo pacman -S ffmpeg mpv deno android-tools zenity
```

**zenity** нужен для диалога выбора папки.

### Установка

Одним файлом: соберите установщик и запустите его, двойным кликом или из терминала.

```
installer/build.sh
./dist/SaltMusic-Setup-<версия>.run
```

Мастер:

- установит программу в `~/.local/share/salt-music/app`;
- проверит системные пакеты и предложит поставить недостающие через pacman;
- создаст ярлык в меню и команду `salt-music`.

Удаление: пункт меню «Uninstall Salt Music» или `SaltMusic-Setup-<версия>.run --uninstall`.
Без вопросов: `--unattended`.

Вручную, для разработки (нужен Python 3.11+):

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
./salt-music.sh
```

## Если YouTube пишет «подтвердите, что вы не бот»

В настройках → «Прочее» выберите браузер, где вы вошли в YouTube: cookies будут браться оттуда.

На Windows Chrome и Edge шифруют cookies и держат их базу открытой, поэтому yt-dlp часто
не может их прочитать. Подойдёт Firefox, или файл `cookies.txt`: выгрузите его
расширением вроде «Get cookies.txt LOCALLY» и выберите в «Файл cookies.txt».
Выбранный файл важнее браузера.

Программа смотрит только имена cookies, значения никуда не выводятся и не пишутся в журнал.

## Где что хранится

| Что | Windows | Linux |
|---|---|---|
| Настройки | `%APPDATA%\SaltMusic\settings.json` | `~/.config/salt-music/settings.json` |
| Архив загрузок, история, жанры, очередь | `%LOCALAPPDATA%\SaltMusic\` | `~/.local/share/salt-music/` |
| Журнал | `%LOCALAPPDATA%\SaltMusic\logs\` | `~/.local/share/salt-music/logs/` |
| Скачанные версии yt-dlp | `%LOCALAPPDATA%\SaltMusic\packages\` | `~/.local/share/salt-music/packages/` |

Переменная `SALT_MUSIC_HOME=<папка>` переносит всё в `<папка>/config` и `<папка>/data`.
Так удобно держать отдельный тестовый профиль.

## Обновление yt-dlp

Кнопка «Обновить yt-dlp» в настройках скачивает свежие `yt-dlp` и `yt-dlp-ejs` с PyPI,
сверяет sha256 и подключает их со следующего запуска. Сама программа при этом не меняется.
«Вернуть встроенный» откатывает обновление.

## Тесты

```
.venv/bin/python -m pytest -q          # Linux
.venv\Scripts\python -m pytest -q      # Windows
```

Тесты работают во временном профиле и не трогают настоящие настройки. Тесты с настоящим
аудио пропускаются без ffmpeg, тест плеера пропускается без mpv.

Проверка интерфейса в браузере:

```
SALT_WEB_PORT=8551 SALT_MUSIC_HOME=.web-profile .venv/bin/python main.py
```
