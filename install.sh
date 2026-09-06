#!/bin/bash
# install.sh - One-liner installer for interpreter-v2
# Usage: curl -LsSf https://raw.githubusercontent.com/bquenin/interpreter/main/install.sh | bash
#
# To install somewhere other than your home directory (for example on a second
# drive), set INTERPRETER_HOME first. The choice is remembered for upgrades:
#   INTERPRETER_HOME=/mnt/data/interpreter curl -LsSf https://raw.githubusercontent.com/bquenin/interpreter/main/install.sh | bash

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
echo -e "${GRAY}Plan for at least 6 GB of free disk space, including first-run model downloads.${NC}"
echo ""

# Resolve the install location. INTERPRETER_HOME wins; otherwise reuse the
# location recorded by a previous run so plain re-runs upgrade in place. The
# layout under the root mirrors src/interpreter/paths.py; keep them in sync:
#   <root>/uv/tools    tool environment      <root>/uv-cache  install downloads
#   <root>/uv/python   uv-managed Python     <root>/models    HuggingFace cache
CONFIG_DIR="$HOME/.interpreter"
INSTALL_ROOT_FILE="$CONFIG_DIR/install-dir"
PREVIOUS_ROOT=""
if [ -f "$INSTALL_ROOT_FILE" ]; then
	PREVIOUS_ROOT=$(tr -d '\r\n' <"$INSTALL_ROOT_FILE")
	PREVIOUS_ROOT="${PREVIOUS_ROOT%/}"
fi

INSTALL_ROOT="${INTERPRETER_HOME:-$PREVIOUS_ROOT}"
UV_CACHE_ARGS=()
if [ -n "$INSTALL_ROOT" ]; then
	# Expand a leading ~ and make relative paths absolute.
	INSTALL_ROOT="${INSTALL_ROOT/#\~/$HOME}"
	case "$INSTALL_ROOT" in
	/*) ;;
	*) INSTALL_ROOT="$PWD/$INSTALL_ROOT" ;;
	esac
	INSTALL_ROOT="${INSTALL_ROOT%/}"
	if [ -z "$INSTALL_ROOT" ]; then
		echo -e "${RED}Error: INTERPRETER_HOME must be a directory, not the filesystem root. Try /opt/interpreter${NC}"
		exit 1
	fi
	mkdir -p "$INSTALL_ROOT"
	export UV_TOOL_DIR="$INSTALL_ROOT/uv/tools"
	export UV_PYTHON_INSTALL_DIR="$INSTALL_ROOT/uv/python"
	# Keep the multi-gigabyte package downloads off the home drive too, and
	# remove them after the install instead of leaving them in uv's cache.
	INSTALL_CACHE_DIR="$INSTALL_ROOT/uv-cache"
	UV_CACHE_ARGS=(--cache-dir "$INSTALL_CACHE_DIR")
	MODELS_DIR="$INSTALL_ROOT/models"
	echo -e "${GRAY}Install location: $INSTALL_ROOT${NC}"
else
	INSTALL_CACHE_DIR=""
	MODELS_DIR=""
	echo -e "${GRAY}Install location: home directory (set INTERPRETER_HOME to choose another drive)${NC}"
fi
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

# When the install location changes, remove the tool environment from the old
# location first. Otherwise the reinstall would leave a multi-gigabyte orphan.
if [ "$PREVIOUS_ROOT" != "$INSTALL_ROOT" ]; then
	if [ -n "$PREVIOUS_ROOT" ]; then
		PREVIOUS_TOOL_DIR="$PREVIOUS_ROOT/uv/tools"
	else
		PREVIOUS_TOOL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools"
	fi
	if [ -d "$PREVIOUS_TOOL_DIR/interpreter-v2" ]; then
		echo -e "${YELLOW}     Removing the previous installation from $PREVIOUS_TOOL_DIR${NC}"
		UV_TOOL_DIR="$PREVIOUS_TOOL_DIR" uv tool uninstall interpreter-v2 >/dev/null 2>&1 || true
		rm -rf "$PREVIOUS_TOOL_DIR/interpreter-v2"
		if [ -n "$PREVIOUS_ROOT" ]; then
			echo -e "${GRAY}     Models downloaded by the previous installation remain in $PREVIOUS_ROOT/models${NC}"
			echo -e "${GRAY}     Delete that folder once the new installation works.${NC}"
		else
			echo -e "${GRAY}     Models downloaded by the previous installation remain in the HuggingFace cache${NC}"
			echo -e "${GRAY}     (~/.cache/huggingface/hub). Delete the models--rtr46--* and models--entai2965--*${NC}"
			echo -e "${GRAY}     folders there once the new installation works.${NC}"
		fi
	fi
fi

# Install or upgrade interpreter-v2
echo -e "${YELLOW}[2/${TOTAL_STEPS}] Installing interpreter-v2 from PyPI...${NC}"
echo -e "${GRAY}     (this may take a minute on first install)${NC}"
# Use Python 3.12 - uv-managed Python includes tkinter, system Python 3.13+ often doesn't
INSTALL_OK=1
uv tool install --upgrade --python 3.12 "${UV_CACHE_ARGS[@]}" interpreter-v2 2>&1 || INSTALL_OK=0
if [ -n "$INSTALL_CACHE_DIR" ]; then
	uv cache clean --cache-dir "$INSTALL_CACHE_DIR" >/dev/null 2>&1 || true
	rm -rf "$INSTALL_CACHE_DIR"
fi
if [ "$INSTALL_OK" -ne 1 ]; then
	echo ""
	echo -e "${RED}Installation failed!${NC}"
	echo -e "${YELLOW}This may be due to missing dependencies. Try:${NC}"
	echo -e "  uv python install 3.12"
	echo -e "  Then run this installer again."
	exit 1
fi
uv tool update-shell >/dev/null 2>&1 || true

# Record the install location so upgrades, the app, and the uninstaller find it.
if [ -n "$INSTALL_ROOT" ]; then
	mkdir -p "$CONFIG_DIR"
	printf '%s' "$INSTALL_ROOT" >"$INSTALL_ROOT_FILE"
fi

# Pre-compile bytecode and warm up OS caches
echo -e "${YELLOW}[3/${TOTAL_STEPS}] Optimizing for fast startup...${NC}"
TOOL_DIR="${UV_TOOL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools}/interpreter-v2"
if [ -d "$TOOL_DIR" ]; then
	# Compile bytecode (exclude .tmpl.py template files that aren't valid Python)
	"$TOOL_DIR/bin/python" -m compileall -q -x '\.tmpl\.py$' "$TOOL_DIR/lib" 2>/dev/null || true
	# Warm up OS caches by running once
	interpreter-v2 --list-windows >/dev/null 2>&1 || true
fi

# Check Linux runtime dependencies (Linux only)
# Always check regardless of WAYLAND_DISPLAY - some compositors like gamescope don't set it
if [[ "$(uname)" == "Linux" ]]; then
	echo -e "${YELLOW}[4/${TOTAL_STEPS}] Checking Linux runtime dependencies...${NC}"

	if ldconfig -p 2>/dev/null | grep -q libpipewire-0.3; then
		echo -e "${GREEN}     PipeWire library available${NC}"
	else
		echo -e "${YELLOW}     libpipewire-0.3 not found. Wayland capture may not work.${NC}"
		echo -e "${GRAY}     Install with: apt install libpipewire-0.3-0 (Debian/Ubuntu)${NC}"
		echo -e "${GRAY}                   dnf install pipewire (Fedora)${NC}"
		echo -e "${GRAY}                   pacman -S pipewire (Arch)${NC}"
	fi

	# Qt 6.5+ requires libxcb-cursor for the xcb platform plugin used on X11/XWayland.
	# The GUI cannot launch without it, so treat this as a hard failure rather than a warning.
	if ldconfig -p 2>/dev/null | grep -q libxcb-cursor; then
		echo -e "${GREEN}     libxcb-cursor available${NC}"
	else
		echo -e "${RED}     libxcb-cursor not found. The Qt GUI cannot launch without it.${NC}"
		echo -e "${YELLOW}     Install it and re-run this installer:${NC}"
		echo -e "${CYAN}       sudo apt install libxcb-cursor0      ${GRAY}(Debian/Ubuntu/Mint)${NC}"
		echo -e "${CYAN}       sudo dnf install xcb-util-cursor     ${GRAY}(Fedora)${NC}"
		echo -e "${CYAN}       sudo pacman -S xcb-util-cursor       ${GRAY}(Arch)${NC}"
		exit 1
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
if [ -n "$INSTALL_ROOT" ]; then
	echo -e "${GRAY}Installed to $INSTALL_ROOT (models will download to $MODELS_DIR)${NC}"
	echo ""
fi
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
