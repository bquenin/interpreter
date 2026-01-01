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

# Detect OS
OS="$(uname -s)"

echo ""
echo -e "${CYAN}=== interpreter-v2 Installer ===${NC}"
echo "Offline screen translator for Japanese retro games"
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}[1/4] Installing uv package manager...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Add uv to PATH for this session
    export PATH="$HOME/.local/bin:$PATH"

    # Verify uv is now available
    if ! command -v uv &> /dev/null; then
        echo -e "${RED}Error: uv installation failed. Please restart your terminal and try again.${NC}"
        exit 1
    fi
    echo -e "${GREEN}uv installed successfully!${NC}"
else
    echo -e "${GREEN}[1/4] uv is already installed${NC}"
fi

# Linux/Wayland: Install build tools BEFORE interpreter (needed for pynput/evdev)
NEEDS_LOGOUT=false
WAYLAND_SETUP_FAILED=false
if [ "$OS" = "Linux" ] && [ -n "$WAYLAND_DISPLAY" ]; then
    echo -e "${YELLOW}[2/4] Setting up Wayland keyboard support...${NC}"

    # Check if build tools are needed (try to find cc)
    if ! command -v cc &> /dev/null; then
        echo -e "${GRAY}     Installing build tools for pynput...${NC}"

        # Detect distro and install build tools
        INSTALL_OK=false
        if command -v apt &> /dev/null; then
            sudo apt install -y build-essential && INSTALL_OK=true
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y gcc gcc-c++ make && INSTALL_OK=true
        elif command -v pacman &> /dev/null; then
            sudo pacman -S --noconfirm base-devel && INSTALL_OK=true
        elif command -v zypper &> /dev/null; then
            sudo zypper install -y gcc gcc-c++ make && INSTALL_OK=true
        elif command -v apk &> /dev/null; then
            sudo apk add build-base && INSTALL_OK=true
        fi

        if [ "$INSTALL_OK" = false ]; then
            echo -e "${YELLOW}     Could not install build tools automatically.${NC}"
            echo -e "${YELLOW}     Keyboard shortcuts may not work on Wayland.${NC}"
            echo -e "${YELLOW}     To fix later: install gcc/build-essential manually.${NC}"
            WAYLAND_SETUP_FAILED=true
        fi
    else
        echo -e "${GREEN}     Build tools already installed${NC}"
    fi

    # Add user to input group if not already
    if ! groups | grep -q '\binput\b'; then
        echo -e "${GRAY}     Adding $USER to input group...${NC}"
        if sudo usermod -a -G input "$USER" 2>/dev/null; then
            NEEDS_LOGOUT=true
        else
            echo -e "${YELLOW}     Could not add to input group (needs sudo).${NC}"
            echo -e "${YELLOW}     To fix: sudo usermod -a -G input $USER${NC}"
            WAYLAND_SETUP_FAILED=true
        fi
    else
        echo -e "${GREEN}     Already in input group${NC}"
    fi

    if [ "$WAYLAND_SETUP_FAILED" = false ]; then
        echo -e "${GREEN}     Wayland keyboard support configured!${NC}"
    fi
else
    if [ "$OS" = "Linux" ]; then
        echo -e "${GREEN}[2/4] Linux/X11 detected - no extra setup needed${NC}"
    else
        echo -e "${GREEN}[2/4] macOS detected - no extra setup needed${NC}"
    fi
fi

# Install or upgrade interpreter-v2
echo -e "${YELLOW}[3/4] Installing interpreter-v2 from GitHub...${NC}"
echo -e "${GRAY}     (this may take a minute on first install)${NC}"
uv tool install --upgrade "git+https://github.com/bquenin/interpreter@main" 2>&1 || true
uv tool update-shell > /dev/null 2>&1 || true

# Pre-compile bytecode and warm up OS caches
echo -e "${YELLOW}[4/4] Optimizing for fast startup...${NC}"
TOOL_DIR="$HOME/.local/share/uv/tools/interpreter-v2"
if [ -d "$TOOL_DIR" ]; then
    # Compile bytecode
    "$TOOL_DIR/bin/python" -m compileall -q "$TOOL_DIR/lib" 2>/dev/null || true
    # Warm up OS caches (Gatekeeper, dyld) by running once
    interpreter-v2 --list-windows > /dev/null 2>&1 || true
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

if [ "$NEEDS_LOGOUT" = true ]; then
    echo -e "${YELLOW}IMPORTANT: Log out and back in for keyboard${NC}"
    echo -e "${YELLOW}shortcuts to work on Wayland.${NC}"
    echo ""
fi

echo "To start, run:"
echo ""
echo -e "  ${CYAN}interpreter-v2${NC}"
echo ""
echo "You may need to restart your terminal first."
echo ""
