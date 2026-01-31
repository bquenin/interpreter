#!/bin/bash
# install.sh - One-liner installer for interpreter-v2
# Usage: curl -LsSf https://raw.githubusercontent.com/bquenin/interpreter/main/install.sh | bash

set -e

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
GRAY='\033[0;90m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Determine total steps (Linux has extra steps)
if [[ "$(uname)" == "Linux" ]]; then
	TOTAL_STEPS=5
else
	TOTAL_STEPS=3
fi

echo ""
echo -e "${CYAN}=== interpreter-v2 Installer ===${NC}"
echo "Offline screen translator for Japanese retro games"
echo ""

# Check if uv is installed
if ! command -v uv &>/dev/null; then
	echo -e "${YELLOW}[1/${TOTAL_STEPS}] Installing uv package manager...${NC}"
	curl -LsSf https://astral.sh/uv/install.sh | sh

	# Add uv to PATH for this session
	export PATH="$HOME/.local/bin:$PATH"

	# Verify uv is now available
	if ! command -v uv &>/dev/null; then
		echo -e "${RED}Error: uv installation failed. Please restart your terminal and try again.${NC}"
		exit 1
	fi
	echo -e "${GREEN}uv installed successfully!${NC}"
else
	echo -e "${GREEN}[1/${TOTAL_STEPS}] uv is already installed${NC}"
fi

# Install or upgrade interpreter-v2
echo -e "${YELLOW}[2/${TOTAL_STEPS}] Installing interpreter-v2 from PyPI...${NC}"
echo -e "${GRAY}     (this may take a minute on first install)${NC}"
# Use Python 3.12 - uv-managed Python includes tkinter, system Python 3.13+ often doesn't
if ! uv tool install --upgrade --python 3.12 interpreter-v2 2>&1; then
	echo ""
	echo -e "${RED}Installation failed!${NC}"
	echo -e "${YELLOW}This may be due to missing dependencies. Try:${NC}"
	echo -e "  uv python install 3.12"
	echo -e "  Then run this installer again."
	exit 1
fi
uv tool update-shell >/dev/null 2>&1 || true

# Pre-compile bytecode and warm up OS caches
echo -e "${YELLOW}[3/${TOTAL_STEPS}] Optimizing for fast startup...${NC}"
TOOL_DIR="$HOME/.local/share/uv/tools/interpreter-v2"
if [ -d "$TOOL_DIR" ]; then
	# Compile bytecode (exclude .tmpl.py template files that aren't valid Python)
	"$TOOL_DIR/bin/python" -m compileall -q -x '\.tmpl\.py$' "$TOOL_DIR/lib" 2>/dev/null || true
	# Warm up OS caches by running once
	interpreter-v2 --list-windows >/dev/null 2>&1 || true
fi

# Check Wayland dependencies (Linux only)
# Always check regardless of WAYLAND_DISPLAY - some compositors like gamescope don't set it
if [[ "$(uname)" == "Linux" ]]; then
	echo -e "${YELLOW}[4/${TOTAL_STEPS}] Checking Wayland capture dependencies...${NC}"

	if ldconfig -p 2>/dev/null | grep -q libpipewire-0.3; then
		echo -e "${GREEN}     PipeWire library available${NC}"
	else
		echo -e "${YELLOW}     libpipewire-0.3 not found. Wayland capture may not work.${NC}"
		echo -e "${GRAY}     Install with: apt install libpipewire-0.3-0 (Debian/Ubuntu)${NC}"
		echo -e "${GRAY}                   dnf install pipewire (Fedora)${NC}"
		echo -e "${GRAY}                   pacman -S pipewire (Arch)${NC}"
	fi
fi

# Install desktop entry and icon (Linux only)
if [[ "$(uname)" == "Linux" ]]; then
	echo -e "${YELLOW}[5/${TOTAL_STEPS}] Installing desktop entry...${NC}"

	# Find the installed icon
	ICON_SRC=$(find "$TOOL_DIR/lib" -name "icon.png" -path "*/resources/icons/*" 2>/dev/null | head -1)

	if [ -n "$ICON_SRC" ]; then
		# Install icon using xdg-icon-resource if available, otherwise fall back to manual copy
		if command -v xdg-icon-resource &>/dev/null; then
			xdg-icon-resource install --novendor --size 256 "$ICON_SRC" interpreter-v2
		else
			mkdir -p "$HOME/.local/share/icons/hicolor/256x256/apps"
			cp "$ICON_SRC" "$HOME/.local/share/icons/hicolor/256x256/apps/interpreter-v2.png"
			gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
		fi
		# Install desktop entry
		mkdir -p "$HOME/.local/share/applications"
		cat >"$HOME/.local/share/applications/interpreter-v2.desktop" <<'EOF'
[Desktop Entry]
Name=Interpreter
Comment=Offline screen translator for Japanese games
Exec=interpreter-v2
Icon=interpreter-v2
Type=Application
Categories=Utility;Translation;
StartupWMClass=interpreter-v2
EOF

		update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

		echo -e "${GREEN}Desktop entry installed${NC}"
	else
		echo -e "${GRAY}Skipping desktop entry (icon not found)${NC}"
	fi
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "To start, run:"
echo ""
echo -e "  ${CYAN}interpreter-v2${NC}"
echo ""
if [[ "$(uname)" == "Linux" ]]; then
	echo -e "${YELLOW}Hotkeys:${NC} To use global hotkeys, add yourself to the input group:"
	echo ""
	echo -e "  ${CYAN}sudo usermod -aG input \$USER${NC}"
	echo ""
	echo "Then log out and back in."
	echo ""
fi
echo "You may need to restart your terminal first."
echo ""
