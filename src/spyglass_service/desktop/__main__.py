"""Entry point of the desktop app: `python -m spyglass_service.desktop`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from spyglass_service import __version__
from spyglass_service.desktop.datadir import check_data_dir


def _check_data_dir(path: str) -> int:
    """Print why a data folder is unsuitable (if it is) and return the verdict as an exit code.

    must_exist=False because the installer runs this before it creates the folder.
    """
    verdict, message = check_data_dir(Path(path), __version__, must_exist=False)
    if message:
        print(message)
    return int(verdict)


def main(argv: list[str] | None = None) -> int:
    """Run the desktop app, or just check a data folder when --check-data-dir is given."""
    parser = argparse.ArgumentParser(prog="spyglass", description="Spyglass desktop app")
    parser.add_argument("--check-data-dir", metavar="PATH",
                        help="check that PATH suits this version; exit 0, 3 (older data) or 4 (newer)")
    parser.add_argument("--background", action="store_true",
                        help="start without opening the interface in the browser")
    args = parser.parse_args(argv)
    if args.check_data_dir is not None:
        return _check_data_dir(args.check_data_dir)
    # Imported here so the folder check stays fast and free of the launcher's heavy imports.
    from spyglass_service.desktop.launcher import Launcher

    return Launcher(open_browser=not args.background).run()


if __name__ == "__main__":
    sys.exit(main())
