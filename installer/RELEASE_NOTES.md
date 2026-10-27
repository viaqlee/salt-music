## Windows 10/11 (64-bit)

**Установщик:** скачайте `SaltMusic-Setup-{version}.exe` и запустите. Права администратора не нужны. Установщик предложит поставить через winget то, чего нет на компьютере: FFmpeg, Deno, adb (отправка на телефон) и mpv (плеер).

**Без установки:** `SaltMusic-{version}-portable.zip`. Распакуйте и запустите `SaltMusic.exe`. FFmpeg и Deno тогда нужно поставить самому:

```
winget install Gyan.FFmpeg DenoLand.Deno Google.PlatformTools shinchiro.mpv
```

Windows может предупредить о неизвестном издателе: программа не подписана. Нажмите «Подробнее» → «Выполнить в любом случае».

## Linux

**Установщик:** скачайте `SaltMusic-Setup-{version}.run` и запустите двойным кликом или из терминала:

```
bash SaltMusic-Setup-{version}.run
```

Нужны Python 3.11+ и интернет: зависимости ставятся в отдельное окружение. Программа ставится в `~/.local/share/salt-music/app`, появляются ярлык в меню и команда `salt-music`. Права root не нужны. Системные программы мастер проверит сам и предложит поставить недостающие; вручную на Arch:

```
sudo pacman -S ffmpeg mpv deno android-tools zenity
```

Удаление: пункт меню «Uninstall Salt Music» или `bash SaltMusic-Setup-{version}.run --uninstall`. Без вопросов: `--unattended`.

---

Контрольные суммы всех файлов лежат в `SHA256SUMS.txt`.
