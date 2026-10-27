"""Salt Music entry point.

The order matters: logging first (a windowed .exe has no console), then process
identity and tool paths, then the yt-dlp update folder, and only then anything
that imports yt_dlp (the UI does).
"""

import os
import sys


def main() -> None:
    from salt_music import desktop, logs, tools, updater
    from salt_music.paths import app_dir

    logs.setup()
    desktop.setup_process()
    tools.setup_path()
    try:
        version = updater.activate()
    except OSError:
        version = None
    if version:
        logs.log.info("using downloaded yt-dlp %s", version)
    # a shortcut may start us in any folder; never resolve anything relative to it
    try:
        os.chdir(app_dir())
    except OSError:
        pass

    from salt_music.ui.app import run

    try:
        run()
    except Exception:
        logs.log.exception("fatal error")
        raise


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        sys.exit("Salt Music needs Python 3.11 or newer")
    main()
