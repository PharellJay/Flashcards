"""Textual user interface for the flashcard app."""

from __future__ import annotations

import random

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Grid, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Static,
    TextArea,
    Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from models import AGAIN, DONE, ROOT_ID, Card, Store, StoreError


def _one_line(text: str, width: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


# ---------------------------------------------------------------- modals


class TextPrompt(ModalScreen[str | None]):
    """Ask for a single line of text (folder names)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, value: str = "") -> None:
        super().__init__()
        self.prompt_title = title
        self.value = value

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.prompt_title, classes="dialog-title")
            yield Input(value=self.value, id="text")
            with Horizontal(classes="buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    @on(Input.Submitted)
    @on(Button.Pressed, "#ok")
    def submit(self) -> None:
        self.dismiss(self.query_one("#text", Input).value)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class CreateFolderDialog(ModalScreen[tuple[str, str] | None]):
    """Ask for a folder name and where to put it. Returns (parent_id, name)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+l", "change_location", "Change location", priority=True),
    ]

    def __init__(self, store: Store, parent_id: str) -> None:
        super().__init__()
        self.store = store
        self.parent_id = parent_id

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Create folder", classes="dialog-title")
            yield Label("Name")
            yield Input(id="name")
            with Horizontal(id="location-row"):
                yield Label(id="location")
                yield Button("Change (ctrl+l)", id="change")
            with Horizontal(classes="buttons"):
                yield Button("Create", variant="primary", id="create")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.update_location()
        self.query_one("#name", Input).focus()

    def update_location(self) -> None:
        where = "(top level)" if self.parent_id == ROOT_ID else self.store.path_of(self.parent_id)
        self.query_one("#location", Label).update(f"Location: [b]{where}[/b]")

    @on(Button.Pressed, "#change")
    def action_change_location(self) -> None:
        def picked(dest: str | None) -> None:
            if dest is not None:
                self.parent_id = dest
                self.update_location()
            self.query_one("#name", Input).focus()

        self.app.push_screen(FolderPicker(self.store, "Create folder in…"), picked)

    @on(Input.Submitted)
    @on(Button.Pressed, "#create")
    def submit(self) -> None:
        self.dismiss((self.parent_id, self.query_one("#name", Input).value))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class CardForm(ModalScreen[tuple[str, str] | None]):
    """Edit the front/back of a card."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]

    def __init__(self, title: str, front: str = "", back: str = "") -> None:
        super().__init__()
        self.form_title = title
        self.front = front
        self.back = back

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label(self.form_title, classes="dialog-title")
            yield Label("Front")
            yield TextArea(self.front, id="front", classes="card-text")
            yield Label("Back")
            yield TextArea(self.back, id="back", classes="card-text")
            yield Label("[dim]ctrl+s to save · tab to switch field · esc to cancel[/]")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        for area in self.query(TextArea):
            area.tab_behavior = "focus"

    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        self.dismiss(
            (self.query_one("#front", TextArea).text, self.query_one("#back", TextArea).text)
        )

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class Confirm(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape,n", "no", "No"),
        Binding("y", "yes", "Yes"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.message, classes="dialog-title")
            with Horizontal(classes="buttons"):
                yield Button("Yes (y)", variant="error", id="yes")
                yield Button("No (n)", id="no")

    @on(Button.Pressed, "#yes")
    def action_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def action_no(self) -> None:
        self.dismiss(False)


class FolderPicker(ModalScreen[str | None]):
    """Pick a destination folder. Folders in `exclude_subtree` are hidden."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self, store: Store, title: str, exclude_subtree: str | None = None, allow_root: bool = True
    ) -> None:
        super().__init__()
        self.store = store
        self.picker_title = title
        self.exclude = exclude_subtree
        self.allow_root = allow_root

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label(self.picker_title, classes="dialog-title")
            label = "(top level)" if self.allow_root else "[dim]All folders[/]"
            tree: Tree[str] = Tree(label, data=ROOT_ID, id="picker")
            tree.show_root = True
            tree.guide_depth = 3
            self._fill(tree.root, ROOT_ID)
            tree.root.expand_all()
            yield tree
            yield Label("[dim]enter to choose · esc to cancel[/]")

    def _fill(self, node: TreeNode[str], folder_id: str) -> None:
        for cid in self.store.folders[folder_id].children:
            if cid == self.exclude:
                continue
            child = node.add(self.store.folders[cid].name, data=cid, allow_expand=True)
            self._fill(child, cid)
            if not child.children:
                child.allow_expand = False

    def on_mount(self) -> None:
        tree = self.query_one(Tree)
        tree.auto_expand = False
        tree.focus()

    @on(Tree.NodeSelected)
    def chosen(self, event: Tree.NodeSelected[str]) -> None:
        if event.node.data == ROOT_ID and not self.allow_root:
            self.notify("Choose a folder, not the root.", severity="warning")
            return
        self.dismiss(event.node.data)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------- study


class StudyScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "leave", "Back"),
        Binding("space", "flip", "Show answer / next"),
        Binding("1", "grade(1)", "Again", show=False),
        Binding("2", "grade(2)", "Done", show=False),
        Binding("right", "next", "Next", show=False),
    ]

    def __init__(self, store: Store, cards: list[Card], cram: bool, title: str) -> None:
        super().__init__()
        self.store = store
        self.queue = list(cards)
        self.cram = cram
        self.study_title = title
        self.total = len(cards)
        self.done = 0
        self.revealed = False
        self.tally = {AGAIN: 0, DONE: 0}

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="study"):
            yield Static(id="progress")
            with Center(id="faces"):
                yield Static(id="front", classes="face")
                yield Static(id="back", classes="face")
            yield Static(id="hint")
            with Horizontal(id="grades"):
                for grade, label, variant in ((AGAIN, "1 Again", "error"), (DONE, "2 Done", "success")):
                    button = Button(label, variant=variant, id=f"grade-{grade}")
                    button.can_focus = False
                    yield button
        yield Footer()

    def on_mount(self) -> None:
        mode = "Cram" if self.cram else "Review"
        self.sub_title = f"{mode} · {self.study_title}"
        self.show_card()

    @property
    def current(self) -> Card | None:
        return self.queue[0] if self.queue else None

    def show_card(self) -> None:
        progress = self.query_one("#progress", Static)
        front = self.query_one("#front", Static)
        back = self.query_one("#back", Static)
        hint = self.query_one("#hint", Static)
        grades = self.query_one("#grades")
        card = self.current
        grades.display = card is not None and self.revealed and not self.cram
        hint.display = not grades.display
        if card is None:
            progress.update("")
            back.display = False
            if self.cram:
                front.update(f"[b]Finished![/b]\n\nYou went through {self.total} card(s).")
            else:
                front.update(
                    f"[b]Session complete![/b]\n\n[green]{self.tally[DONE]} card(s) done[/]"
                    f" · [red]{self.tally[AGAIN]} again[/]"
                )
            hint.update("[dim]esc to go back[/]")
            return
        remaining = len(self.queue)
        progress.update(
            f"[dim]{self.store.path_of(card.folder_id)}[/]   "
            f"{remaining} card(s) left · {self.done} done"
        )
        front.update(Text(card.front))
        back.update(Text(card.back or "(empty)"))
        back.display = self.revealed
        if not self.revealed:
            hint.update("[b]space[/]/[b]click[/] show answer")
        elif self.cram:
            hint.update("[b]space[/]/[b]click[/]/[b]→[/] next card")

    @on(Button.Pressed, "#grades Button")
    def grade_pressed(self, event: Button.Pressed) -> None:
        self.action_grade(int(event.button.id.removeprefix("grade-")))

    def on_click(self, event: events.Click) -> None:
        if event.button == 1:
            self.action_flip()

    def action_flip(self) -> None:
        if self.current is None:
            return
        if not self.revealed:
            self.revealed = True
            self.show_card()
        elif self.cram:
            self.action_next()

    def action_next(self) -> None:
        if self.cram and self.revealed and self.current is not None:
            self.queue.pop(0)
            self.done += 1
            self.revealed = False
            self.show_card()

    def action_grade(self, grade: int) -> None:
        card = self.current
        if self.cram or card is None or not self.revealed:
            return
        self.store.review(card.id, grade)
        self.tally[grade] += 1
        self.done += 1
        self.queue.pop(0)
        if grade == AGAIN:
            # see it again later in this session
            self.queue.insert(min(len(self.queue), 3), card)
        self.revealed = False
        self.show_card()

    def action_leave(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------- main


class FlashcardApp(App[None]):
    TITLE = "Flashcards"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (120, "-wide")]
    VERTICAL_BREAKPOINTS = [(0, "-short"), (30, "-tall")]
    CSS = """
    #main { height: 1fr; }
    #left { width: 40%; min-width: 28; }
    #folders { height: 1fr; border: round $primary-darken-2; }
    .toolbar { height: auto; grid-size: 2; grid-rows: 3; grid-gutter: 0 1; padding: 0 1; }
    .toolbar Button { width: 1fr; min-width: 0; }
    /* wide terminals: study and card actions each fit on a single row */
    Screen.-wide #study-bar, Screen.-wide #card-bar { grid-size: 4; }
    /* short terminals: compact one-line buttons so the card list keeps its space */
    Screen.-short .toolbar { grid-rows: 1; grid-gutter: 1 1; margin-bottom: 1; }
    #folders:focus-within { border: round $accent; }
    #right { width: 1fr; }
    #info { height: auto; padding: 0 1; border: round $primary-darken-2; }
    #cards { height: 1fr; min-height: 5; border: round $primary-darken-2; }
    #cards:focus { border: round $accent; }
    #preview { height: auto; max-height: 40%; padding: 0 1; border: round $primary-darken-2; }

    ModalScreen { align: center middle; }
    .dialog {
        width: 60; max-width: 100%; height: auto; max-height: 90%;
        padding: 1 2; border: thick $accent; background: $surface;
    }
    .dialog.wide { width: 80; }
    .dialog-title { width: 100%; text-style: bold; margin-bottom: 1; }
    .dialog #picker { height: auto; max-height: 20; }
    .card-text { height: 6; }
    .buttons { height: auto; margin-top: 1; align-horizontal: right; }
    .buttons Button { margin-left: 1; }
    #location-row { height: auto; margin-top: 1; }
    #location { width: 1fr; height: 3; content-align: left middle; }

    #study { align: center middle; padding: 1 4; }
    #progress { width: 100%; content-align: center middle; margin-bottom: 1; }
    .face {
        width: 100; max-width: 100%; height: auto; min-height: 5;
        padding: 1 2; border: round $accent; content-align: center middle;
        text-align: center;
    }
    #back { border: round $success; margin-top: 1; }
    #hint { width: 100%; content-align: center middle; margin-top: 1; }
    #grades { width: 100%; height: auto; align-horizontal: center; margin-top: 1; }
    #grades Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("n", "create_folder", "Create folder"),
        Binding("r", "rename_folder", "Rename"),
        Binding("m", "move_folder", "Move folder"),
        Binding("a", "add_card", "Add card"),
        Binding("e", "edit_card", "Edit card"),
        Binding("M", "move_card", "Move card"),
        Binding("d", "delete", "Delete"),
        Binding("s", "study", "Study due"),
        Binding("c", "cram", "Cram"),
        Binding("f5", "make_due", "Refresh folder"),
        Binding("R", "make_all_due", "Refresh all"),
        Binding("q", "quit", "Quit"),
    ]

    # main-screen actions (everything bound above except quit)
    MAIN_ACTIONS = frozenset(b.action for b in BINDINGS if b.action != "quit")

    def __init__(self, store: Store) -> None:
        super().__init__()
        self.store = store

    # ----- layout

    @staticmethod
    def _tool(label: str, action: str, tip: str, variant: str = "default") -> Button:
        button = Button(
            label, variant, id=f"btn-{action}", action=f"app.{action}", tooltip=tip
        )
        button.can_focus = False  # keep keyboard focus on the tree / card list
        return button

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left"):
                tree: Tree[str] = Tree("All folders", data=ROOT_ID, id="folders")
                tree.border_title = "Folders"
                tree.auto_expand = False
                yield tree
                with Grid(id="folder-bar", classes="toolbar"):
                    yield self._tool("+ New folder", "create_folder", "Create a folder (n)", "primary")
                    yield self._tool("✎ Rename", "rename_folder", "Rename this folder (r)")
                    yield self._tool("→ Move", "move_folder", "Move this folder somewhere else (m)")
                    yield self._tool("✕ Delete", "delete_folder", "Delete this folder and everything in it (d)", "error")
            with Vertical(id="right"):
                yield Static(id="info")
                with Grid(id="study-bar", classes="toolbar"):
                    yield self._tool("▶ Study", "study", "Review the cards that are due (s)", "success")
                    yield self._tool("⟳ Cram all", "cram", "Go through every card, shuffled (c)")
                    yield self._tool("↻ Refresh", "make_due", "Make every card in this folder due again (F5)")
                    yield self._tool("↻ Refresh all", "make_all_due", "Make every card in every folder due again (R)")
                cards = OptionList(id="cards")
                cards.border_title = "Cards (this folder)"
                yield cards
                with Grid(id="card-bar", classes="toolbar"):
                    yield self._tool("+ Add card", "add_card", "Add a card to this folder (a)", "primary")
                    yield self._tool("✎ Edit", "edit_card", "Edit the highlighted card (e / enter)")
                    yield self._tool("→ Move", "move_card", "Move the highlighted card to another folder (M)")
                    yield self._tool("✕ Delete", "delete_card", "Delete the highlighted card (d in card list)", "error")
                preview = Static(id="preview")
                preview.border_title = "Preview"
                yield preview
        yield Footer()

    def on_resize(self, event: events.Resize) -> None:
        short = event.size.height < 30  # matches the "-short" breakpoint
        for button in self.query(".toolbar Button"):
            button.compact = short

    def on_mount(self) -> None:
        self.refresh_tree(ROOT_ID)
        self.query_one(Tree).focus()

    # ----- helpers

    @property
    def tree(self) -> Tree[str]:
        return self.query_one("#folders", Tree)

    @property
    def card_list(self) -> OptionList:
        return self.query_one("#cards", OptionList)

    def selected_folder(self) -> str:
        node = self.tree.cursor_node
        if node is None or node.data not in self.store.folders:
            return ROOT_ID
        return node.data

    def selected_card(self) -> Card | None:
        ol = self.card_list
        if ol.highlighted is None or ol.option_count == 0:
            return None
        return self.store.cards.get(ol.get_option_at_index(ol.highlighted).id)

    def _label(self, folder_id: str, name: str) -> Text:
        due, total = self.store.counts(folder_id)
        label = Text(name, style="bold" if folder_id == ROOT_ID else "")
        label.append(f"  {total}", style="dim")
        if due:
            label.append(f" ·{due} due", style="green")
        return label

    def refresh_tree(self, select_id: str | None = None, select_card: str | None = None) -> None:
        tree = self.tree
        select_id = select_id or self.selected_folder()
        expanded = {ROOT_ID}
        stack = [tree.root]
        while stack:
            node = stack.pop()
            if node.is_expanded and node.data:
                expanded.add(node.data)
            stack.extend(node.children)
        # make sure the selected folder is visible
        cur = self.store.folders.get(select_id)
        while cur is not None and cur.parent_id is not None:
            expanded.add(cur.parent_id)
            cur = self.store.folders.get(cur.parent_id)

        tree.clear()
        tree.root.set_label(self._label(ROOT_ID, "All folders"))
        target: TreeNode[str] = tree.root

        def build(node: TreeNode[str], folder_id: str) -> None:
            nonlocal target
            for cid in self.store.folders[folder_id].children:
                f = self.store.folders[cid]
                child = node.add(self._label(cid, f.name), data=cid, allow_expand=bool(f.children))
                if cid == select_id:
                    target = child
                build(child, cid)
                if cid in expanded:
                    child.expand()

        build(tree.root, ROOT_ID)
        tree.root.expand()
        self.call_after_refresh(tree.move_cursor, target)
        self.refresh_right(target.data, select_card)

    def refresh_right(self, folder_id: str | None = None, select_card: str | None = None) -> None:
        folder_id = folder_id or self.selected_folder()
        if folder_id not in self.store.folders:
            folder_id = ROOT_ID
        f = self.store.folders[folder_id]
        due, total = self.store.counts(folder_id)
        info = self.query_one("#info", Static)
        info.update(
            f"[b]{self.store.path_of(folder_id)}[/b]\n"
            f"{len(f.children)} subfolder(s) · {total} card(s) · [green]{due} due[/]"
        )
        ol = self.card_list
        ol.clear_options()
        if f.cards:
            cards = [self.store.cards[cid] for cid in f.cards]
            ol.add_options(
                Option(Text.assemble(("● ", "green") if c.due else "  ", _one_line(c.front)), id=c.id)
                for c in cards
            )
            ol.highlighted = f.cards.index(select_card) if select_card in f.cards else 0
        else:
            hint = "Select a folder to see its cards" if folder_id == ROOT_ID else "No cards yet — press 'a' to add one"
            ol.add_option(Option(Text(hint, style="dim"), disabled=True))
        self.update_folder_buttons(folder_id, due, total)
        self.update_preview()

    def update_preview(self) -> None:
        card = self.selected_card()
        preview = self.query_one("#preview", Static)
        if card is None:
            preview.update("[dim]—[/]")
        else:
            preview.update(
                Text.assemble(("Front: ", "bold"), card.front, "\n", ("Back:  ", "bold"), card.back)
                + Text("\ndue" if card.due else "\ndone — refresh to study it again", style="dim")
            )
        has_card = card is not None
        for action in ("edit_card", "move_card", "delete_card"):
            self.query_one(f"#btn-{action}", Button).disabled = not has_card

    def update_folder_buttons(self, folder_id: str, due: int, total: int) -> None:
        """Enable only the folder/study buttons that make sense for the selected folder."""
        for action in ("rename_folder", "move_folder", "delete_folder", "add_card"):
            self.query_one(f"#btn-{action}", Button).disabled = folder_id == ROOT_ID
        study = self.query_one("#btn-study", Button)
        study.label = f"▶ Study ({due} due)"
        study.disabled = due == 0
        self.query_one("#btn-cram", Button).disabled = total == 0
        self.query_one("#btn-make_due", Button).disabled = due == total
        all_due, all_total = self.store.counts(ROOT_ID)
        self.query_one("#btn-make_all_due", Button).disabled = all_due == all_total

    def _try(self, fn, *args):
        """Run a store operation; show its error and return None if it fails."""
        try:
            return fn(*args)
        except StoreError as exc:
            self.notify(str(exc), severity="error")
            return None

    # ----- events

    @on(Tree.NodeHighlighted, "#folders")
    def folder_highlighted(self, event: Tree.NodeHighlighted[str]) -> None:
        self.refresh_right(event.node.data)

    @on(OptionList.OptionHighlighted, "#cards")
    def card_highlighted(self) -> None:
        self.update_preview()

    @on(OptionList.OptionSelected, "#cards")
    def card_selected(self) -> None:
        self.action_edit_card()

    # ----- folder actions

    def action_create_folder(self) -> None:
        def done(result: tuple[str, str] | None) -> None:
            if result is not None and (folder := self._try(self.store.create_folder, *result)):
                self.refresh_tree(folder.id)

        self.push_screen(CreateFolderDialog(self.store, self.selected_folder()), done)

    def action_rename_folder(self) -> None:
        fid = self.selected_folder()
        if fid == ROOT_ID:
            self.notify("Select a folder to rename.", severity="warning")
            return

        def done(name: str | None) -> None:
            if name is not None and self._try(self.store.rename_folder, fid, name):
                self.refresh_tree(fid)

        self.push_screen(TextPrompt("Rename folder", self.store.folders[fid].name), done)

    def action_move_folder(self) -> None:
        fid = self.selected_folder()
        if fid == ROOT_ID:
            self.notify("Select a folder to move.", severity="warning")
            return

        def done(dest: str | None) -> None:
            if dest is not None and self._try(self.store.move_folder, fid, dest):
                self.refresh_tree(fid)
                self.notify(f"Moved to {self.store.path_of(fid)}")

        name = self.store.folders[fid].name
        self.push_screen(
            FolderPicker(self.store, f"Move '{name}' into…", exclude_subtree=fid), done
        )

    # ----- card actions

    def action_add_card(self) -> None:
        fid = self.selected_folder()
        if fid == ROOT_ID:
            self.notify("Select (or create) a folder first.", severity="warning")
            return

        def done(result: tuple[str, str] | None) -> None:
            if result is not None and (card := self._try(self.store.add_card, fid, *result)):
                self.refresh_tree(fid, select_card=card.id)

        self.push_screen(CardForm(f"New card in {self.store.path_of(fid)}"), done)

    def action_edit_card(self) -> None:
        card = self.selected_card()
        if card is None:
            self.notify("Highlight a card in the card list first (tab).", severity="warning")
            return

        def done(result: tuple[str, str] | None) -> None:
            if result is not None and self._try(self.store.edit_card, card.id, *result):
                self.refresh_right(card.folder_id, select_card=card.id)

        self.push_screen(CardForm("Edit card", card.front, card.back), done)

    def action_move_card(self) -> None:
        card = self.selected_card()
        if card is None:
            self.notify("Highlight a card in the card list first (tab).", severity="warning")
            return

        def done(dest: str | None) -> None:
            if dest is not None and self._try(self.store.move_card, card.id, dest):
                self.refresh_tree()
                self.notify(f"Card moved to {self.store.path_of(dest)}")

        self.push_screen(FolderPicker(self.store, "Move card into…", allow_root=False), done)

    def action_delete(self) -> None:
        """`d` deletes the highlighted card when the card list has focus, else the folder."""
        if self.focused is self.card_list:
            self.action_delete_card()
        else:
            self.action_delete_folder()

    def action_delete_card(self) -> None:
        card = self.selected_card()
        if card is None:
            self.notify("Highlight a card to delete.", severity="warning")
            return

        def done(ok: bool | None) -> None:
            if ok:
                self.store.delete_card(card.id)
                self.refresh_tree()

        self.push_screen(Confirm(f"Delete card '{_one_line(card.front, 40)}'?"), done)

    def action_delete_folder(self) -> None:
        fid = self.selected_folder()
        if fid == ROOT_ID:
            self.notify("Select a folder to delete.", severity="warning")
            return
        f = self.store.folders[fid]
        n_sub = len(self.store.subtree(fid)) - 1
        n_cards = len(self.store.cards_in(fid))
        parent = f.parent_id

        def done(ok: bool | None) -> None:
            if ok:
                self.store.delete_folder(fid)
                self.refresh_tree(parent)

        self.push_screen(
            Confirm(
                f"Delete folder '{f.name}' with {n_sub} subfolder(s) and {n_cards} card(s)?"
            ),
            done,
        )

    # ----- study

    def _start(self, cram: bool) -> None:
        fid = self.selected_folder()
        cards = self.store.study_cards(fid) if cram else self.store.due_cards(fid)
        if not cards:
            msg = "No cards here yet." if cram else "Nothing due here — try cram (c)."
            self.notify(msg, severity="warning")
            return
        random.shuffle(cards)
        self.push_screen(
            StudyScreen(self.store, cards, cram, self.store.path_of(fid)),
            lambda _: self.refresh_tree(fid),
        )

    # ----- refresh

    def action_make_due(self) -> None:
        self._make_due(self.selected_folder())

    def action_make_all_due(self) -> None:
        self._make_due(ROOT_ID)

    def _make_due(self, fid: str) -> None:
        due, total = self.store.counts(fid)
        waiting = total - due
        if not waiting:
            self.notify("Every card here is already due.")
            return
        where = "in all folders" if fid == ROOT_ID else f"in {self.store.path_of(fid)}"

        def done(ok: bool | None) -> None:
            if ok:
                n = self.store.make_due(fid)
                self.refresh_tree()
                self.notify(f"{n} card(s) are due again.")

        self.push_screen(Confirm(f"Make {waiting} card(s) {where} due again?"), done)

    def action_study(self) -> None:
        self._start(cram=False)

    def action_cram(self) -> None:
        self._start(cram=True)

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        # main-screen actions shouldn't fire while a modal/study screen is active
        if action in self.MAIN_ACTIONS and len(self.screen_stack) > 1:
            return False
        return True
