<img src="assets/icon.svg" width="96" alt="">

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

Программу, поставленную позже, Salt Music найдёт сама примерно за 10 секунд, перезапуск не нужен.

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

Релизы собирает GitHub Actions (`.github/workflows/release.yml`) по тегу `v<версия>`: установщик для Windows и `.run` для Linux.
Пуш в `main` собирает и проверяет всё то же самое, но ничего не публикует.

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

## Программа не находит ffmpeg, adb, mpv или Deno

Программы ищутся в папке Salt Music, в папках winget (и в `Links`, и в распакованных
пакетах), scoop, chocolatey, Android SDK, `Program Files` (mpv из winget стоит в `Program Files\MPV Player`)
и там, куда программы записаны в реестре Windows (App Paths, «Открыть с помощью», список установленных). На Linux ещё в `~/.local/bin`,
`/usr/local/bin`, `/usr/bin`, `/snap/bin`. Потом в PATH; на Windows PATH читается и из реестра,
так что программа, поставленная при открытом Salt Music, находится без перезапуска системы.

Если программа лежит где-то ещё, укажите её в настройках → «Прочее» → «Программы»:
можно выбрать сам файл или папку с ним (или с подпапкой `bin`). ffprobe берётся рядом с ffmpeg.
«Искать автоматически» сбрасывает указанный путь.

## Обновление программы

Salt Music сам проверяет GitHub при запуске и раз в шесть часов. Кнопка над строкой ссылки
загорается, когда вышла новая версия. По нажатию программа скачивает установщик из релиза,
сверяет его с `SHA256SUMS.txt`, закрывается, ставит новую версию поверх и запускается снова.
Настройки, музыка и история не трогаются. Если новее только yt-dlp, обновляется он.

Так обновляются копии, поставленные установщиком (`.exe` на Windows, `.run` на Linux),
начиная с 0.3.0. Переносная копия Windows скачивает установщик и открывает его мастер: после этого
программа установлена как обычно и дальше обновляется сама. Для запуска из исходников кнопка открывает страницу релиза.

## Где что хранится

| Что | Windows | Linux |
|---|---|---|
| Настройки | `%APPDATA%\SaltMusic\settings.json` | `~/.config/salt-music/settings.json` |
| Архив загрузок, история, жанры, очередь | `%LOCALAPPDATA%\SaltMusic\` | `~/.local/share/salt-music/` |
| Журнал | `%LOCALAPPDATA%\SaltMusic\logs\` | `~/.local/share/salt-music/logs/` |
| Скачанные версии yt-dlp | `%LOCALAPPDATA%\SaltMusic\packages\` | `~/.local/share/salt-music/packages/` |
| Скачанный установщик обновления | `%LOCALAPPDATA%\SaltMusic\updates\` | `~/.local/share/salt-music/updates/` |

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
