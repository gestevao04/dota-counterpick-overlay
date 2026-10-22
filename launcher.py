"""Entry point of the packaged Windows program (DotaDraftOverlay.exe).

The packaged program has no console window, so errors would vanish silently.
This wrapper writes any crash to error.log in the data folder and shows a
message box. `--selftest` is used by the build pipeline: it checks that every
library the program needs made it into the package.
"""

import sys
import traceback

import paths


def selftest():
    problems = []
    for name in ("cv2", "numpy", "mss", "requests", "certifi", "tkinter", "tkinter.ttk"):
        try:
            __import__(name)
        except Exception as exc:
            problems.append(f"import {name}: {exc}")
    try:
        import tkinter

        tkinter.Tcl().eval("info patchlevel")        # proves the Tcl/Tk files are bundled
    except Exception as exc:
        problems.append(f"Tcl/Tk: {exc}")
    try:
        import counter_score, draft_assistant, draft_overlay, draft_reader, updater, version  # noqa: F401
    except Exception as exc:
        problems.append(f"program modules: {exc}")
    else:
        slots = (paths.data_dir() / "slots.json", paths.resource_dir() / "slots.json")
        if not any(p.exists() for p in slots):
            problems.append("slots.json is missing")
        else:
            draft_assistant.use_slots_file()
            if len(draft_reader.SLOTS) != 10:
                problems.append("slots.json does not define ten slots")
    if problems:
        report = "selftest FAILED:\n" + "\n".join(problems)
    else:
        report = f"selftest ok (version {version.__version__}, frozen={paths.frozen()})"
    # no console in the packaged program, so leave the result in a file
    (paths.data_dir() / "selftest.txt").write_text(report + "\n")
    return 1 if problems else 0


def _report_crash(text):
    try:
        (paths.data_dir() / "error.log").write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        from tkinter import Tk, messagebox

        root = Tk()
        root.withdraw()
        last = text.strip().splitlines()[-1] if text.strip() else "unknown error"
        messagebox.showerror(
            "Dota Draft Overlay",
            "The program hit an error and has to close.\n"
            f"Details were saved to error.log in:\n{paths.data_dir()}\n\n{last}",
        )
        root.destroy()
    except Exception:
        pass


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        import draft_overlay

        draft_overlay.main()
    except SystemExit:
        raise
    except Exception:
        _report_crash(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
