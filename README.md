# WaySnap

A lightweight, open-source screenshot tool for Linux — inspired by ShareX and Flameshot.
Built with Python 3 and PyQt6, designed for both X11 and Wayland.

## Features

- Runs in the system tray
- Global hotkey **Ctrl+PrintScreen** triggers capture from anywhere
- Capture a custom region by dragging a selection rectangle
- Capture a specific monitor on multi-display setups
- 8-handle resize + drag-to-move the selection
- Annotation tools: pencil, arrow, rectangle, ellipse, text
- Floating toolbar appears next to your selection
- Saves to `~/Pictures/WaySnap/waysnap_YYYY-MM-DD_HH-MM-SS.png`
- Copies the result to the clipboard automatically

## System dependencies

| Environment | Tool | Install |
|---|---|---|
| GNOME Wayland | `gnome-screenshot` | `sudo apt install gnome-screenshot` |
| KDE Wayland | `spectacle` | `sudo apt install kde-spectacle` |
| wlroots (Sway, Hyprland) | `grim` | `sudo apt install grim` |
| X11 | `maim` | `sudo apt install maim` |

Only one tool is needed depending on your desktop environment.

> **GNOME Wayland + hotkey:** GNOME intercepts the bare `PrintScreen` key.
> To let `Ctrl+PrintScreen` reach WaySnap, disable the conflicting shortcut:
> **Settings → Keyboard → Keyboard Shortcuts → Screenshots → disable "Take a screenshot"**

## Installation

```bash
git clone https://github.com/vovafes/WaySnap.git
cd WaySnap
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Usage

### Selection

| Action | Result |
|---|---|
| Left-click tray icon | Take screenshot |
| Right-click tray icon | Open menu |
| Drag on overlay | Draw selection |
| Drag corner / edge handle | Resize selection |
| Drag inside selection | Move selection |
| `Enter` or `Space` | Save & copy to clipboard |
| Double-click | Save & copy to clipboard |

### Annotation tools

| Key | Tool | Description |
|---|---|---|
| `S` | ⬚ Select | Draw / adjust the capture region |
| `P` | ✏ Pencil | Freehand drawing |
| `A` | ➤ Arrow | Draw an arrow between two points |
| `R` | □ Rectangle | Draw a rectangle |
| `E` | ○ Ellipse | Draw an ellipse |
| `T` | T Text | Click to place a text label |

Use the toolbar (appears below your selection) to pick a tool, change colour, and adjust line width.

### Other shortcuts

| Key | Result |
|---|---|
| `Ctrl+Z` | Undo last annotation |
| `Esc` (1st) | Cancel active text input |
| `Esc` (2nd) | Clear all annotations |
| `Esc` (3rd) | Clear selection |
| `Esc` (4th) | Close overlay |

## Project structure

```
WaySnap/
├── main.py                  # Entry point
└── waysnap/
    ├── tray.py              # TrayIconManager — menu, capture chain, save
    ├── canvas.py            # AnnotationCanvas — selection overlay + annotation toolbar
    ├── shapes.py            # Shape model — Stroke, Arrow, Rect, Ellipse, Text
    ├── hotkey.py            # HotkeyManager — global Ctrl+PrintScreen listener
    └── portal_helper.py     # XDG Desktop Portal screenshot helper (subprocess)
```
