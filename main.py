"""Punto de entrada de TVPlayout PRO."""
import sys
import traceback


def _fatal(msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "TVPlayout PRO — error", 0x10)
    except Exception:  # noqa: BLE001
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    try:
        from app.main_window import main
    except ImportError as e:
        _fatal("Falta una dependencia: %s\n\nEjecuta INSTALL.bat (instala PySide6)." % e)
        sys.exit(1)
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        try:
            from app import logger
            logger.get("main").error("Excepción no controlada:\n%s", tb)
        except Exception:  # noqa: BLE001
            pass
        _fatal("Error inesperado:\n\n" + tb[-1500:])
        sys.exit(1)
