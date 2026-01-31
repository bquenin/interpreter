#!/bin/bash
# uninstall.sh - Uninstaller for interpreter-v2
# Usage: curl -LsSf https://raw.githubusercontent.com/bquenin/interpreter/main/uninstall.sh | bash

set -e

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
GRAY='\033[0;90m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}=== interpreter-v2 Uninstaller ===${NC}"
echo ""

# Check if uv is installed
if ! command -v uv &>/dev/null; then
	echo -e "${YELLOW}uv is not installed. Nothing to uninstall.${NC}"
	exit 0
fi

# Check if interpreter-v2 is installed
if ! uv tool list 2>/dev/null | grep -q "interpreter-v2"; then
	echo -e "${YELLOW}interpreter-v2 is not installed.${NC}"
else
	echo -e "${YELLOW}[1/3] Uninstalling interpreter-v2...${NC}"
	uv tool uninstall interpreter-v2
	echo -e "${GREEN}interpreter-v2 uninstalled${NC}"
fi

# Remove desktop entry and icon (Linux only)
if [[ "$(uname)" == "Linux" ]]; then
	echo -e "${YELLOW}[2/3] Removing desktop entry and icon...${NC}"

	DESKTOP_FILE="$HOME/.local/share/applications/interpreter-v2.desktop"
	ICON_FILE="$HOME/.local/share/icons/hicolor/256x256/apps/interpreter-v2.png"

	if [ -f "$DESKTOP_FILE" ]; then
		rm -f "$DESKTOP_FILE"
		echo -e "${GREEN}     Removed desktop entry${NC}"
	else
		echo -e "${GRAY}     Desktop entry not found${NC}"
	fi

	if command -v xdg-icon-resource &>/dev/null; then
		xdg-icon-resource uninstall --size 256 interpreter-v2 2>/dev/null &&
			echo -e "${GREEN}     Removed icon${NC}" ||
			echo -e "${GRAY}     Icon not found${NC}"
	elif [ -f "$ICON_FILE" ]; then
		rm -f "$ICON_FILE"
		gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
		echo -e "${GREEN}     Removed icon${NC}"
	else
		echo -e "${GRAY}     Icon not found${NC}"
	fi

	# Update desktop database
	update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
else
	echo -e "${GRAY}[2/3] Skipping desktop entry removal (not Linux)${NC}"
fi

# Remove user data
echo -e "${YELLOW}[3/3] Removing user data...${NC}"

CONFIG_DIR="$HOME/.interpreter"
MODELS_DIR="$HOME/.cache/huggingface/hub"

# Remove config
if [ -d "$CONFIG_DIR" ]; then
	rm -rf "$CONFIG_DIR"
	echo -e "${GREEN}     Removed config directory${NC}"
else
	echo -e "${GRAY}     Config directory not found${NC}"
fi

# Remove cached models
INTERPRETER_MODELS=$(find "$MODELS_DIR" -maxdepth 1 -type d -name "models--bquenin--*" 2>/dev/null || true)
if [ -n "$INTERPRETER_MODELS" ]; then
	echo "$INTERPRETER_MODELS" | while read -r model; do
		rm -rf "$model"
		echo -e "${GREEN}     Removed $(basename "$model")${NC}"
	done
else
	echo -e "${GRAY}     Cached models not found${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Uninstall complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
