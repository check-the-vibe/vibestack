# XTerm Configuration

The container includes customized XTerm settings for better usability.

## Features Configured
- **Copy/Paste**: Ctrl+Shift+C to copy, Ctrl+Shift+V to paste
- **Color Scheme**: Black background with green text for classic terminal look
- **Font**: DejaVu Sans Mono, size 12
- **Scrollback**: 2000 lines with scrollbar enabled

## Keyboard Shortcuts
- `Ctrl+Shift+C`: Copy selected text to clipboard
- `Ctrl+Shift+V`: Paste from clipboard

## Configuration Files
- `.Xresources`: Contains XTerm appearance and behavior settings
- Loaded automatically on fluxbox startup via `xrdb` command