Версия для Windows 10/11 (64-bit).

**Установщик:** скачайте `SaltMusic-Setup-{version}.exe` и запустите. Права администратора не нужны. Установщик предложит поставить через winget то, чего нет на компьютере: FFmpeg, Deno, adb (отправка на телефон) и mpv (плеер).

**Без установки:** `SaltMusic-{version}-portable.zip`. Распакуйте и запустите `SaltMusic.exe`. FFmpeg и Deno тогда нужно поставить самому:

```
winget install Gyan.FFmpeg DenoLand.Deno Google.PlatformTools shinchiro.mpv
```

Windows может предупредить о неизвестном издателе: программа не подписана. Нажмите «Подробнее» → «Выполнить в любом случае». Контрольные суммы лежат в `SHA256SUMS.txt`.

На Linux эта версия запускается из исходников (`main.py`), см. README. Установщик для Linux пока остаётся в релизе 0.1.
