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
    echo -e "${YELLOW}[1/2] Installing uv package manager...${NC}"
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
    echo -e "${GREEN}[1/2] uv is already installed${NC}"
fi

# Install or upgrade interpreter-v2
echo -e "${YELLOW}[2/2] Installing interpreter-v2 from GitHub...${NC}"
echo -e "${GRAY}     (this may take a minute on first install)${NC}"
uv tool install --upgrade "git+https://github.com/bquenin/interpreter@0f0f07965c7d079795ab3fd315862420c6d3f4bd" 2>&1 || true
uv tool update-shell > /dev/null 2>&1 || true

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
