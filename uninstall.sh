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

# A custom install location (see install.sh) holds the tool environment, the
# uv-managed Python, and the model cache. INTERPRETER_HOME wins over the pointer
# file the installer wrote, matching the app and the installer.
CONFIG_DIR="$HOME/.interpreter"
INSTALL_ROOT_FILE="$CONFIG_DIR/install-dir"
INSTALL_ROOT="${INTERPRETER_HOME:-}"
if [ -z "$INSTALL_ROOT" ] && [ -f "$INSTALL_ROOT_FILE" ]; then
	INSTALL_ROOT=$(tr -d '\r\n' <"$INSTALL_ROOT_FILE")
fi
if [ -n "$INSTALL_ROOT" ]; then
	INSTALL_ROOT="${INSTALL_ROOT/#\~/$HOME}"
	case "$INSTALL_ROOT" in
	/*) ;;
	*) INSTALL_ROOT="$PWD/$INSTALL_ROOT" ;;
	esac
	INSTALL_ROOT="${INSTALL_ROOT%/}"
fi
if [ -n "$INSTALL_ROOT" ]; then
	export UV_TOOL_DIR="$INSTALL_ROOT/uv/tools"
	export UV_PYTHON_INSTALL_DIR="$INSTALL_ROOT/uv/python"
	echo -e "${GRAY}Install location: $INSTALL_ROOT${NC}"
	echo ""
fi

# Uninstall the tool. Without uv, fall back to removing its files directly.
echo -e "${YELLOW}[1/4] Uninstalling interpreter-v2...${NC}"
TOOL_ROOT="${UV_TOOL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools}"
if command -v uv &>/dev/null; then
	REPORTED_TOOL_ROOT=$(uv tool dir 2>/dev/null || true)
	if [ -n "$REPORTED_TOOL_ROOT" ]; then
		TOOL_ROOT="$REPORTED_TOOL_ROOT"
	fi
	if uv tool list 2>/dev/null | grep -q "interpreter-v2"; then
		uv tool uninstall interpreter-v2
		echo -e "${GREEN}     interpreter-v2 uninstalled${NC}"
	else
		echo -e "${GRAY}     interpreter-v2 is not registered with uv${NC}"
	fi
else
	echo -e "${YELLOW}     uv was not found; cleaning up its files directly${NC}"
fi
if [ -d "$TOOL_ROOT/interpreter-v2" ]; then
	rm -rf "$TOOL_ROOT/interpreter-v2"
	echo -e "${GREEN}     Removed stale tool environment${NC}"
fi
if [ -n "$INSTALL_ROOT" ]; then
	# An install that was later moved to a custom location may have left the
	# default environment and its package downloads behind.
	DEFAULT_TOOL_ENV="${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools/interpreter-v2"
	if [ -d "$DEFAULT_TOOL_ENV" ]; then
		rm -rf "$DEFAULT_TOOL_ENV"
		echo -e "${GREEN}     Removed tool environment left in the home directory${NC}"
	fi
	rm -rf "$INSTALL_ROOT/uv-cache"
fi

# Remove desktop entry and icon (Linux only)
if [[ "$(uname)" == "Linux" ]]; then
	echo -e "${YELLOW}[2/4] Removing desktop entry and icon...${NC}"

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
	echo -e "${GRAY}[2/4] Skipping desktop entry removal (not Linux)${NC}"
fi

# Remove user data
echo -e "${YELLOW}[3/4] Removing user data...${NC}"

if [ -n "${HF_HUB_CACHE:-}" ]; then
	MODELS_DIR="$HF_HUB_CACHE"
elif [ -n "${HF_HOME:-}" ]; then
	MODELS_DIR="$HF_HOME/hub"
else
	MODELS_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/huggingface/hub"
fi

# Remove config (this also removes the install location pointer)
if [ -d "$CONFIG_DIR" ]; then
	rm -rf "$CONFIG_DIR"
	echo -e "${GREEN}     Removed config directory${NC}"
else
	echo -e "${GRAY}     Config directory not found${NC}"
fi

# Remove the repositories actually downloaded by interpreter-v2. Retain the
# legacy bquenin pattern for caches created by older releases. With a custom
# install location the models live under it and are removed below, but an
# install that was moved there later may have left models in this cache.
REMOVED_MODEL=0
if [ -d "$MODELS_DIR" ]; then
	for MODEL_NAME in \
		"models--rtr46--meiki.text.detect.v0" \
		"models--rtr46--meiki.txt.recognition.v0" \
		"models--entai2965--sugoi-v4-ja-en-ctranslate2"; do
		if [ -d "$MODELS_DIR/$MODEL_NAME" ]; then
			rm -rf "$MODELS_DIR/$MODEL_NAME"
			echo -e "${GREEN}     Removed $MODEL_NAME${NC}"
			REMOVED_MODEL=1
		fi
		rm -rf "$MODELS_DIR/.locks/$MODEL_NAME"
	done
	LEGACY_MODELS=$(find "$MODELS_DIR" -maxdepth 1 -type d -name "models--bquenin--*" 2>/dev/null || true)
	if [ -n "$LEGACY_MODELS" ]; then
		echo "$LEGACY_MODELS" | while read -r model; do
			rm -rf "$model" "$MODELS_DIR/.locks/$(basename "$model")"
			echo -e "${GREEN}     Removed $(basename "$model")${NC}"
		done
		REMOVED_MODEL=1
	fi
fi
if [ "$REMOVED_MODEL" -eq 0 ]; then
	echo -e "${GRAY}     Cached models not found${NC}"
fi

# Remove the custom install location. Only the folders the installer creates
# are deleted, and the root itself only once it is empty, so a root shared with
# other files (or pointed at the wrong place) is never wiped wholesale.
echo -e "${YELLOW}[4/4] Removing install location...${NC}"
if [ -n "$INSTALL_ROOT" ]; then
	if [ -d "$INSTALL_ROOT/uv" ]; then
		rm -rf "$INSTALL_ROOT/uv"
		echo -e "${GREEN}     Removed tool environment and Python${NC}"
	fi
	if [ -d "$INSTALL_ROOT/models" ]; then
		rm -rf "$INSTALL_ROOT/models"
		echo -e "${GREEN}     Removed downloaded models${NC}"
	fi
	if [ -d "$INSTALL_ROOT" ]; then
		if rmdir "$INSTALL_ROOT" 2>/dev/null; then
			echo -e "${GREEN}     Removed install location $INSTALL_ROOT${NC}"
		else
			echo -e "${GRAY}     Kept $INSTALL_ROOT because it still contains other files${NC}"
		fi
	fi
else
	echo -e "${GRAY}     No custom install location${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Uninstall complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
