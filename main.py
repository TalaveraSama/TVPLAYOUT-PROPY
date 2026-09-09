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
        if getattr(sys, "frozen", False):
            hint = "Copia la carpeta completa de distribución, incluida _internal."
        else:
            hint = "Ejecuta INSTALL.bat para instalar PySide6 y PyAV."
        _fatal("Falta una dependencia: %s\n\n%s" % (e, hint))
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
