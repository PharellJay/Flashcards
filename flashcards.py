"""Flashcards — a terminal flashcard app with nested folders."""

import json
import sys
from pathlib import Path

from models import Store
from ui import FlashcardApp

DATA_FILE = Path(__file__).resolve().parent / "data.json"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_FILE
    try:
        store = Store.load(path)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"Could not read {path}: {exc}", file=sys.stderr)
        backup = path.with_name(path.name + ".bak")
        if backup.exists():
            print(f"The previous version is saved in {backup}.", file=sys.stderr)
        sys.exit(1)
    FlashcardApp(store).run()


if __name__ == "__main__":
    main()
