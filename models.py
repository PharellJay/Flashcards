"""Data model: nested folders of flashcards and JSON persistence."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

ROOT_ID = "root"

AGAIN, DONE = 1, 2


class StoreError(Exception):
    """Raised for invalid operations (bad names, cyclic moves, ...)."""


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Folder:
    id: str
    name: str
    parent_id: str | None
    children: list[str] = field(default_factory=list)
    cards: list[str] = field(default_factory=list)


@dataclass
class Card:
    id: str
    folder_id: str
    front: str
    back: str
    due: bool = True  # only studying clears it; only a user refresh sets it again


def _card_from_json(data: dict) -> Card:
    due = data.get("due", True)
    if isinstance(due, str):  # older files stored a due date: due if it has passed
        due = due <= date.today().isoformat()
    return Card(data["id"], data["folder_id"], data["front"], data["back"], bool(due))


class Store:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else None
        self.folders: dict[str, Folder] = {ROOT_ID: Folder(ROOT_ID, "/", None)}
        self.cards: dict[str, Card] = {}

    # ---------- persistence ----------

    @classmethod
    def load(cls, path: str | os.PathLike) -> "Store":
        store = cls(path)
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            store.folders = {f["id"]: Folder(**f) for f in data.get("folders", [])}
            store.cards = {c["id"]: _card_from_json(c) for c in data.get("cards", [])}
            if ROOT_ID not in store.folders:
                store.folders[ROOT_ID] = Folder(ROOT_ID, "/", None)
        return store

    def save(self) -> None:
        if self.path is None:
            return
        data = {
            "version": 2,
            "folders": [asdict(f) for f in self.folders.values()],
            "cards": [asdict(c) for c in self.cards.values()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".data-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # ---------- folders ----------

    def _check_name(self, parent_id: str, name: str, exclude: str | None = None) -> str:
        name = name.strip()
        if not name:
            raise StoreError("Name cannot be empty.")
        if "/" in name:
            raise StoreError("Name cannot contain '/'.")
        for cid in self.folders[parent_id].children:
            if cid != exclude and self.folders[cid].name.lower() == name.lower():
                raise StoreError(f"A folder named '{name}' already exists here.")
        return name

    def _sorted_children(self, parent_id: str) -> None:
        self.folders[parent_id].children.sort(key=lambda i: self.folders[i].name.lower())

    def create_folder(self, parent_id: str, name: str) -> Folder:
        name = self._check_name(parent_id, name)
        folder = Folder(_new_id(), name, parent_id)
        self.folders[folder.id] = folder
        self.folders[parent_id].children.append(folder.id)
        self._sorted_children(parent_id)
        self.save()
        return folder

    def rename_folder(self, folder_id: str, name: str) -> None:
        if folder_id == ROOT_ID:
            raise StoreError("Cannot rename the root.")
        folder = self.folders[folder_id]
        folder.name = self._check_name(folder.parent_id, name, exclude=folder_id)
        self._sorted_children(folder.parent_id)
        self.save()

    def is_descendant(self, folder_id: str, ancestor_id: str) -> bool:
        """True if folder_id is ancestor_id or lies beneath it."""
        cur: str | None = folder_id
        while cur is not None:
            if cur == ancestor_id:
                return True
            cur = self.folders[cur].parent_id
        return False

    def move_folder(self, folder_id: str, new_parent_id: str) -> None:
        if folder_id == ROOT_ID:
            raise StoreError("Cannot move the root.")
        if self.is_descendant(new_parent_id, folder_id):
            raise StoreError("Cannot move a folder into itself or its own subfolder.")
        folder = self.folders[folder_id]
        if folder.parent_id == new_parent_id:
            return
        self._check_name(new_parent_id, folder.name)
        self.folders[folder.parent_id].children.remove(folder_id)
        self.folders[new_parent_id].children.append(folder_id)
        folder.parent_id = new_parent_id
        self._sorted_children(new_parent_id)
        self.save()

    def delete_folder(self, folder_id: str) -> None:
        if folder_id == ROOT_ID:
            raise StoreError("Cannot delete the root.")
        folder = self.folders[folder_id]
        for sub in self.subtree(folder_id):
            for cid in self.folders.pop(sub).cards:
                del self.cards[cid]
        self.folders[folder.parent_id].children.remove(folder_id)
        self.save()

    def subtree(self, folder_id: str) -> list[str]:
        out, stack = [], [folder_id]
        while stack:
            fid = stack.pop()
            out.append(fid)
            stack.extend(self.folders[fid].children)
        return out

    def path_of(self, folder_id: str) -> str:
        parts = []
        cur: str | None = folder_id
        while cur is not None and cur != ROOT_ID:
            parts.append(self.folders[cur].name)
            cur = self.folders[cur].parent_id
        return "/" + "/".join(reversed(parts))

    # ---------- cards ----------

    def add_card(self, folder_id: str, front: str, back: str) -> Card:
        if folder_id == ROOT_ID:
            raise StoreError("Select a folder first (cards must live in a folder).")
        if not front.strip():
            raise StoreError("Front cannot be empty.")
        card = Card(_new_id(), folder_id, front.strip(), back.strip())
        self.cards[card.id] = card
        self.folders[folder_id].cards.append(card.id)
        self.save()
        return card

    def edit_card(self, card_id: str, front: str, back: str) -> None:
        if not front.strip():
            raise StoreError("Front cannot be empty.")
        card = self.cards[card_id]
        card.front, card.back = front.strip(), back.strip()
        self.save()

    def delete_card(self, card_id: str) -> None:
        card = self.cards.pop(card_id)
        self.folders[card.folder_id].cards.remove(card_id)
        self.save()

    def move_card(self, card_id: str, folder_id: str) -> None:
        if folder_id == ROOT_ID:
            raise StoreError("Cards must live in a folder.")
        card = self.cards[card_id]
        self.folders[card.folder_id].cards.remove(card_id)
        self.folders[folder_id].cards.append(card_id)
        card.folder_id = folder_id
        self.save()

    def cards_in(self, folder_id: str, recursive: bool = True) -> list[Card]:
        ids = self.subtree(folder_id) if recursive else [folder_id]
        return [self.cards[c] for fid in ids for c in self.folders[fid].cards]

    def study_cards(self, folder_id: str) -> list[Card]:
        """Cards studied/refreshed for a folder: only its own cards, or every card for the root."""
        return self.cards_in(folder_id, recursive=folder_id == ROOT_ID)

    def due_cards(self, folder_id: str) -> list[Card]:
        return [c for c in self.study_cards(folder_id) if c.due]

    def counts(self, folder_id: str) -> tuple[int, int]:
        """(due, total) for what studying/refreshing the folder covers."""
        cards = self.study_cards(folder_id)
        return sum(c.due for c in cards), len(cards)

    def make_due(self, folder_id: str) -> int:
        """Make every done card in the folder (every card for the root) due again."""
        cards = [c for c in self.study_cards(folder_id) if not c.due]
        for card in cards:
            card.due = True
        if cards:
            self.save()
        return len(cards)

    # ---------- studying ----------

    def review(self, card_id: str, grade: int) -> None:
        """Again keeps the card due; any other rating marks it done until the user refreshes."""
        if grade == AGAIN:
            return
        self.cards[card_id].due = False
        self.save()
