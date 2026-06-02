# WaySnap

A lightweight, open-source screenshot tool for Linux — inspired by ShareX and Flameshot.
Built with Python 3 and PyQt6, designed for both X11 and Wayland.

## Features

- Runs in the system tray
- Capture a custom region by dragging a selection rectangle
- Capture a specific monitor on multi-display setups
- 8-handle resize + drag-to-move the selection
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

## Installation

```bash
git clone https://github.com/vovafes/WaySnap.git
cd WaySnap
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Usage

| Action | Result |
|---|---|
| Left-click tray icon | Take screenshot |
| Right-click tray icon | Open menu |
| Drag on overlay | Draw selection |
| Drag corner / edge handle | Resize selection |
| Drag inside selection | Move selection |
| `Enter` or `Space` | Save & copy to clipboard |
| `Esc` (first press) | Reset selection |
| `Esc` (second press) | Close overlay |
| Double-click | Save & copy to clipboard |

## Project structure

```
WaySnap/
├── main.py                  # Entry point
└── waysnap/
    ├── tray.py              # TrayIconManager — menu, capture chain, save
    ├── canvas.py            # AnnotationCanvas — fullscreen selection overlay
    └── portal_helper.py     # XDG Desktop Portal screenshot helper (subprocess)
```
