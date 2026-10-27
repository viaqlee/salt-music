# Salt Music для Windows

Та же Salt Music: скачивает треки, альбомы и дискографии с YouTube / YouTube Music
с тегами и обложками, раскладывает по папкам, играет и отправляет музыку на
Android-телефон через adb. Код общий для Windows и Linux, всё платформенное лежит
в `salt_music/desktop/`, `paths.py`, `proc.py` и `tools.py`.

## Установка (для пользователя)

Запустите `SaltMusic-Setup-<версия>.exe`. Права администратора не нужны: программа
ставится в `%LOCALAPPDATA%\Programs\SaltMusic`. На странице задач установщик
предлагает доставить через winget то, чего нет на компьютере:

| Программа | Зачем | winget |
|---|---|---|
| FFmpeg | конвертация звука, обязательно | `Gyan.FFmpeg` |
| Deno | YouTube без него не отдаёт ссылки | `DenoLand.Deno` |
| Android Platform Tools | отправка на телефон | `Google.PlatformTools` |
| mpv | встроенный плеер | `shinchiro.mpv` |

Если программу поставить позже, Salt Music сама найдёт её в течение примерно
10 секунд, перезапуск не нужен.

## Запуск из исходников

Нужен Python 3.11+ (проверено на 3.14).

```bat
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run.bat
```

## Сборка установщика

Нужны Python и [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`ISCC.exe` в PATH
или в стандартной папке).

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
# инструменты внутрь пакета (ffmpeg, deno, adb, mpv), с проверкой sha256 где она опубликована:
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -BundleTools
```

Результат: `dist\SaltMusic-Setup-<версия>.exe`.

## Где что лежит

| Что | Windows | Linux |
|---|---|---|
| Настройки | `%APPDATA%\SaltMusic\settings.json` | `~/.config/salt-music/` |
| История, очередь, архив, жанры | `%LOCALAPPDATA%\SaltMusic\` | `~/.local/share/salt-music/` |
| Журнал | `%LOCALAPPDATA%\SaltMusic\logs\salt-music.log` | `…/salt-music/logs/` |
| Обновления yt-dlp | `%LOCALAPPDATA%\SaltMusic\packages\` | `…/salt-music/packages/` |
| Музыка по умолчанию | папка «Музыка» пользователя | `~/Music` |

`SALT_MUSIC_HOME=<папка>` переносит настройки и данные в `<папка>\config` и
`<папка>\data`. Так удобно держать отдельный тестовый профиль.

## Cookies на Windows

Chrome и Edge шифруют cookies ключом, привязанным к самому браузеру, и держат базу
открытой, пока браузер запущен. yt-dlp часто не может их прочитать. Варианты:

1. **Firefox**: работает, даже когда он открыт.
2. **Файл cookies.txt**: выгрузите расширением вроде «Get cookies.txt LOCALLY» и
   выберите его в настройках → «Прочее» → «Файл cookies.txt». Если файл выбран,
   он важнее браузера.

Программа проверяет только имена cookies (вошли вы или нет), значения никуда не
выводятся и не пишутся в журнал.

## Обновление yt-dlp

Кнопка «Обновить yt-dlp» скачивает свежие колёса `yt-dlp` и `yt-dlp-ejs` с PyPI,
сверяет sha256, распаковывает их с проверкой путей в отдельную папку и подключает
при следующем запуске. Установленная программа при этом не меняется. «Вернуть
встроенный» удаляет скачанную версию.

## Тесты

```bash
.venv/bin/python -m pytest -q          # Linux
.venv\Scripts\python -m pytest -q      # Windows
```

Тесты используют временный профиль и не трогают настоящие настройки. Тесты с
настоящим аудио пропускаются без ffmpeg, а тест плеера пропускается без mpv.

Проверка интерфейса в браузере (отдельный профиль в `.web-profile`):

```bash
SALT_WEB_PORT=8551 SALT_MUSIC_HOME=.web-profile .venv/bin/python main.py
```
