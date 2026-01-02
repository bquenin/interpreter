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

echo ""
echo -e "${CYAN}=== interpreter-v2 Installer ===${NC}"
echo "Offline screen translator for Japanese retro games"
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}[1/3] Installing uv package manager...${NC}"
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
    echo -e "${GREEN}[1/3] uv is already installed${NC}"
fi

# Install or upgrade interpreter-v2
echo -e "${YELLOW}[2/3] Installing interpreter-v2 from GitHub...${NC}"
echo -e "${GRAY}     (this may take a minute on first install)${NC}"
BRANCH="${INTERPRETER_BRANCH:-main}"
# Use Python 3.13 explicitly - onnxruntime doesn't have wheels for 3.14 yet
if ! uv tool install --upgrade --python 3.13 "git+https://github.com/bquenin/interpreter@${BRANCH}" 2>&1; then
    echo ""
    echo -e "${RED}Installation failed!${NC}"
    echo -e "${YELLOW}This may be due to missing dependencies. Try:${NC}"
    echo -e "  uv python install 3.13"
    echo -e "  Then run this installer again."
    exit 1
fi
uv tool update-shell > /dev/null 2>&1 || true

# Pre-compile bytecode and warm up OS caches
echo -e "${YELLOW}[3/3] Optimizing for fast startup...${NC}"
TOOL_DIR="$HOME/.local/share/uv/tools/interpreter-v2"
if [ -d "$TOOL_DIR" ]; then
    # Compile bytecode
    "$TOOL_DIR/bin/python" -m compileall -q "$TOOL_DIR/lib" 2>/dev/null || true
    # Warm up OS caches by running once
    interpreter-v2 --list-windows > /dev/null 2>&1 || true
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
echo "You may need to restart your terminal first."
echo ""
