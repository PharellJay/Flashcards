# Flashcards

A keyboard-friendly flashcard app for the terminal. Organise cards in nested folders, study them, and share whole folders with friends through a short code you can paste into any chat.

Built with Python and [Textual](https://textual.textualize.io/).

```
 ⭘                                         Flashcards                                    ✕ Quit (q)
╭─ Folders ────────────────────────────╮╭──────────────────────────────────────────────────────────╮
│                       ⊟ Collapse all ││ /Biology/Cells                                           │
│▼ All folders  7 ·6 due               ││ 0 subfolder(s) · 3 card(s) · 2 due                       │
│├── ▼ Biology  0                      │╰──────────────────────────────────────────────────────────╯
││   ├── Cells  3 ·2 due               │  ▶ Study (2 due)         ⟳ Cram             ↻ Refresh
││   └── Genetics  1 ·1 due            │
│└── ▼ Spanish  0                      │╭─ Cards (this folder) ────────────────────────────────────╮
│    └── Verbs  3 ·3 due               ││ ● What is the powerhouse of the cell?                    │
│                                      ││   What does the ribosome make?  ✗2                       │
│                                      ││ ● Which organelle holds the DNA?                         │
│                                      │╰──────────────────────────────────────────────────────────╯
│                                      │                         + Add card
│     ⇩ Import           ⇪ Export      │
╰──────────────────────────────────────╯╭─ Preview ────────────────────────────────────────────────╮
              + New folder              │ Front: What does the ribosome make?                      │
                                        │ Back:  Proteins                                          │
               ⋯ Options                │ done — refresh to study it again · missed 2×             │
                                        ╰──────────────────────────────────────────────────────────╯
s Study c Cram f Refresh a Card n Folder o Options z Collapse i Import x Export
```

## Features

- **Nested folders**: as many levels of folders and subfolders as you need. You can create, rename, move and delete them. The tree shows how many cards each folder has and how many are due.
- **Two ways to study**
  - **Study**: goes through the cards that are due. Grade each one **Again** (it comes back later in the session) or **Done** (it's finished until you refresh it).
  - **Cram**: goes through every card in the folder, shuffled and without grading.
- **Choose the side**: before each session you pick whether to see the front and answer with the back, or the other way round. This is handy for vocabulary.
- **Tracks hard cards**: each card counts how often you answered *Again*, shown as `✗N`.
- **Undo**: `u` takes back your last grade while studying, and `ctrl+z` brings back the last deleted card or folder.
- **Share folders**: export a folder (with all its subfolders), or your whole collection, as one line of text. It is copied to your clipboard. Anyone can paste it into **Import** to get the same folders and cards.
- **Remembers your layout**: folders you had open are open again on the next start.
- **Mouse and keyboard**: every action has a button and a hotkey. Right-click a folder or card for its options.
- **Safe saving**: every change is saved right away. The previous version is kept as `data.json.bak`, and a damaged data file gives a clear error message instead of a crash.

## Installation

You need **Python 3.10 or newer**.

```bash
git clone https://github.com/PharellJay/Flashcards.git
cd Flashcards
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
./run.sh                 # uses data.json next to the program
./run.sh my-cards.json   # or any other data file
```

Without the script: `.venv/bin/python flashcards.py [data-file]`. The file is created automatically if it doesn't exist yet.

### Getting started

1. Press **n** to create a folder, such as `Spanish`.
2. Select it and press **a** to add a card. Fill in the front and back, then press **ctrl+s** to save.
3. Press **s** to study, choose which side you want to see first, and press **space** to reveal the answer.
4. Grade the card with **1** (Again) or **2** (Done).
5. When everything is done, press **f** (Refresh) to make the folder's cards due again.

Studying a folder covers only the cards directly in that folder. Selecting **All folders** studies every card.

## Keyboard shortcuts

### Main screen

| Key | Action |
| --- | --- |
| `s` | Study the due cards |
| `c` | Cram: all cards, no grading |
| `f` / `F5` | Refresh: make the folder's cards due again |
| `R` | Refresh every card in every folder |
| `a` | Add a card to the selected folder |
| `n` | New folder |
| `o` | Options for the selected folder or card (also right-click) |
| `r` / `m` / `d` | Rename / move / delete the selected folder |
| `e` / `M` / `d` | Edit / move / delete the selected card (when the card list has focus) |
| `z` | Collapse or expand all folders |
| `i` | Import a share code |
| `x` | Export the selected folder, or everything from **All folders** |
| `ctrl+z` | Undo the last deletion |
| `tab` | Switch between the folder tree and the card list |
| `q` | Quit |

### While studying

| Key | Action |
| --- | --- |
| `space` / click | Show the answer (in cram: next card) |
| `1` / `2` | Grade: Again / Done |
| `→` | Next card (cram) |
| `u` | Undo the last grade |
| `esc` | Back to the main screen |

In dialogs, **esc** cancels. In Yes/No questions, **y**/**n** answer directly and the arrow keys move between the buttons.

## Sharing flashcards

1. Select a folder, or **All folders** to share everything, and press **⇪ Export** (`x`).
   The share code (`flashcards:1:…`) is copied to your clipboard and also shown in a window, in case your terminal doesn't support copying.
2. Send the code to someone, for example in a chat.
3. They select where the cards should go, press **⇩ Import** (`i`), paste the code and press **ctrl+s**.

Share codes contain the folder names and card texts only. Your progress (due cards, miss counts) is not shared. If a folder with the same name already exists, the imported one is renamed to `Name (2)`.

## Your data

Everything is stored in one readable JSON file (`data.json` by default). It holds the folders, the cards with their due state and miss count, and which folders are open. To back up or move your cards, copy that file.

## Project structure

| File | Purpose |
| --- | --- |
| `flashcards.py` | Entry point: loads the data file and starts the app |
| `models.py` | Data model: folders, cards, saving/loading and share codes (no UI code) |
| `ui.py` | The Textual user interface: screens, dialogs and keyboard handling |
| `run.sh` | Starts the app with the project's virtual environment |
| `requirements.txt` | Python dependencies (Textual 8) |

## License

[MIT](LICENSE) © 2026 Pharell Jay Jeyakumar
