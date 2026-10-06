"""Flashcards — a terminal flashcard app with nested folders."""

import sys
from pathlib import Path

from models import Store
from ui import FlashcardApp

DATA_FILE = Path(__file__).resolve().parent / "data.json"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_FILE
    FlashcardApp(Store.load(path)).run()


if __name__ == "__main__":
    main()
