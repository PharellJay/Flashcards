"""Data model: nested folders of flashcards and JSON persistence."""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import tempfile
import uuid
import zlib
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

ROOT_ID = "root"

AGAIN, DONE = 1, 2

SHARE_PREFIX = "flashcards:1:"  # share codes: prefix + base64(zlib(json of the folder tree))


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
    misses: int = 0  # how often it was graded "Again"


def _card_from_json(data: dict) -> Card:
    due = data.get("due", True)
    if isinstance(due, str):  # older files stored a due date: due if it has passed
        due = due <= date.today().isoformat()
    return Card(
        data["id"], data["folder_id"], data["front"], data["back"], bool(due),
        int(data.get("misses", 0)),
    )


class Store:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else None
        self.folders: dict[str, Folder] = {ROOT_ID: Folder(ROOT_ID, "/", None)}
        self.cards: dict[str, Card] = {}
        self.expanded: set[str] = set()  # folders open in the tree, restored on the next start

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
            store.expanded = {fid for fid in data.get("expanded", []) if fid in store.folders}
        return store

    def save(self) -> None:
        if self.path is None:
            return
        data = {
            "version": 2,
            "folders": [asdict(f) for f in self.folders.values()],
            "cards": [asdict(c) for c in self.cards.values()],
            "expanded": sorted(fid for fid in self.expanded if fid in self.folders),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".data-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            if self.path.exists():  # keep the previous version as a last-good copy
                shutil.copy2(self.path, self.path.with_name(self.path.name + ".bak"))
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # ---------- folders ----------

    def check_name(self, parent_id: str, name: str, exclude: str | None = None) -> str:
        """Return the cleaned-up name, or raise StoreError if it can't be used in parent_id."""
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
        name = self.check_name(parent_id, name)
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
        folder.name = self.check_name(folder.parent_id, name, exclude=folder_id)
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
        self.check_name(new_parent_id, folder.name)
        self.folders[folder.parent_id].children.remove(folder_id)
        self.folders[new_parent_id].children.append(folder_id)
        folder.parent_id = new_parent_id
        self._sorted_children(new_parent_id)
        self.save()

    def delete_folder(self, folder_id: str) -> tuple[dict[str, Folder], dict[str, Card]]:
        """Delete a folder with everything in it; returns what was removed, for restore_folder."""
        if folder_id == ROOT_ID:
            raise StoreError("Cannot delete the root.")
        folder = self.folders[folder_id]
        folders, cards = {}, {}
        for sub in self.subtree(folder_id):
            folders[sub] = self.folders.pop(sub)
            for cid in folders[sub].cards:
                cards[cid] = self.cards.pop(cid)
        self.folders[folder.parent_id].children.remove(folder_id)
        self.save()
        return folders, cards

    def restore_folder(self, folders: dict[str, Folder], cards: dict[str, Card]) -> Folder:
        """Put back a folder removed by delete_folder (the first entry is the folder itself)."""
        folder = next(iter(folders.values()))
        if folder.parent_id not in self.folders:
            raise StoreError("Can't restore: its parent folder no longer exists.")
        self.check_name(folder.parent_id, folder.name)
        self.folders.update(folders)
        self.cards.update(cards)
        self.folders[folder.parent_id].children.append(folder.id)
        self._sorted_children(folder.parent_id)
        self.save()
        return folder

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

    # ---------- sharing ----------

    def export_folder(self, folder_id: str) -> str:
        """A one-line share code with the folder, all its subfolders and card texts (no study state).

        For the root it holds every top-level folder instead, i.e. the whole collection.
        """

        def tree(fid: str) -> dict:
            f = self.folders[fid]
            return {
                "name": f.name,
                "cards": [[self.cards[c].front, self.cards[c].back] for c in f.cards],
                "folders": [tree(cid) for cid in f.children],
            }

        if folder_id == ROOT_ID:
            if not self.folders[ROOT_ID].children:
                raise StoreError("There are no folders to export yet.")
            data: dict = {"folders": [tree(cid) for cid in self.folders[ROOT_ID].children]}
        else:
            data = tree(folder_id)
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return SHARE_PREFIX + base64.urlsafe_b64encode(zlib.compress(raw.encode("utf-8"), 9)).decode()

    @staticmethod
    def decode_share_code(code: str) -> list[dict]:
        """Parse and validate a share code into its top-level folders; raises StoreError if it isn't one."""
        bad = StoreError("That doesn't look like a flashcards share code.")
        code = "".join(code.split())  # chat apps may wrap long lines
        if not code.startswith(SHARE_PREFIX):
            raise bad
        try:
            data = json.loads(zlib.decompress(base64.urlsafe_b64decode(code[len(SHARE_PREFIX):])))
        except (binascii.Error, zlib.error, ValueError):
            raise bad from None

        def valid(node: object) -> bool:
            return (
                isinstance(node, dict)
                and isinstance(node.get("name"), str) and node["name"].strip() != ""
                and "/" not in node["name"]
                and isinstance(node.get("cards"), list)
                and all(
                    isinstance(c, list) and len(c) == 2 and all(isinstance(t, str) for t in c)
                    and c[0].strip()
                    for c in node["cards"]
                )
                and isinstance(node.get("folders"), list)
                and all(valid(sub) for sub in node["folders"])
            )

        # a single folder, or {"folders": [...]} for a whole collection exported from the root
        if isinstance(data, dict) and set(data) == {"folders"} and isinstance(data["folders"], list):
            nodes = data["folders"]
        else:
            nodes = [data]
        if not nodes or not all(valid(node) for node in nodes):
            raise bad
        return nodes

    def import_folder(self, parent_id: str, code: str) -> tuple[list[Folder], int]:
        """Add the folder(s) from a share code under parent_id; returns them and the card count.

        A name already used in parent_id gets " (2)", " (3)", ... appended.
        """
        nodes = self.decode_share_code(code)
        taken = {self.folders[c].name.lower() for c in self.folders[parent_id].children}
        for node in nodes:
            base = node["name"].strip()
            name, n = base, 2
            while name.lower() in taken:
                name, n = f"{base} ({n})", n + 1
            node["name"] = name
            taken.add(name.lower())
        count = 0

        def build(node: dict, pid: str) -> Folder:
            nonlocal count
            folder = Folder(_new_id(), node["name"].strip(), pid)
            self.folders[folder.id] = folder
            self.folders[pid].children.append(folder.id)
            self._sorted_children(pid)
            for front, back in node["cards"]:
                card = Card(_new_id(), folder.id, front.strip(), back.strip())
                self.cards[card.id] = card
                folder.cards.append(card.id)
                count += 1
            for sub in node["folders"]:
                build(sub, folder.id)
            return folder

        folders = [build(node, parent_id) for node in nodes]
        self.save()
        return folders, count

    # ---------- cards ----------

    @staticmethod
    def check_front(front: str) -> None:
        if not front.strip():
            raise StoreError("Front cannot be empty.")

    def add_card(self, folder_id: str, front: str, back: str) -> Card:
        if folder_id == ROOT_ID:
            raise StoreError("Select a folder first (cards must live in a folder).")
        self.check_front(front)
        card = Card(_new_id(), folder_id, front.strip(), back.strip())
        self.cards[card.id] = card
        self.folders[folder_id].cards.append(card.id)
        self.save()
        return card

    def edit_card(self, card_id: str, front: str, back: str) -> None:
        self.check_front(front)
        card = self.cards[card_id]
        card.front, card.back = front.strip(), back.strip()
        self.save()

    def delete_card(self, card_id: str) -> tuple[Card, int]:
        """Delete a card; returns it and its position, for restore_card."""
        card = self.cards.pop(card_id)
        siblings = self.folders[card.folder_id].cards
        index = siblings.index(card_id)
        del siblings[index]
        self.save()
        return card, index

    def restore_card(self, card: Card, index: int) -> None:
        """Put back a card removed by delete_card, at its old position."""
        if card.folder_id not in self.folders:
            raise StoreError("Can't restore: its folder no longer exists.")
        self.cards[card.id] = card
        self.folders[card.folder_id].cards.insert(index, card.id)
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

    def reset_misses(self, card_id: str) -> None:
        self.cards[card_id].misses = 0
        self.save()

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
        """Again keeps the card due (and counts a miss); any other rating marks it done until the user refreshes."""
        card = self.cards[card_id]
        if grade == AGAIN:
            card.misses += 1
        else:
            card.due = False
        self.save()

    def set_card_state(self, card_id: str, due: bool, misses: int) -> None:
        """Put a card's study state back (undoing a review)."""
        card = self.cards[card_id]
        card.due, card.misses = due, misses
        self.save()
