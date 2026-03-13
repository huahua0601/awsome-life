#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$SCRIPT_DIR/agent"
DIST_DIR="$SCRIPT_DIR/dist"
STAGING_DIR="$SCRIPT_DIR/.build/deployment_package"

echo "=========================================="
echo "  Building ARM64 deployment package"
echo "=========================================="

# Auto-install uv if missing
if ! command -v uv >/dev/null 2>&1; then
    echo ">>> Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Privilege escalation helper
_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    elif command -v doas >/dev/null 2>&1; then
        doas "$@"
    else
        echo "Warning: no sudo/doas found and not root — trying without privilege escalation..."
        "$@"
    fi
}

# Auto-install zip if missing
if ! command -v zip >/dev/null 2>&1; then
    echo ">>> Installing zip..."
    if command -v pkg >/dev/null 2>&1; then
        _sudo pkg install -y zip
    elif command -v apt-get >/dev/null 2>&1; then
        _sudo apt-get install -y -qq zip
    elif command -v yum >/dev/null 2>&1; then
        _sudo yum install -y zip
    elif command -v dnf >/dev/null 2>&1; then
        _sudo dnf install -y zip
    elif command -v brew >/dev/null 2>&1; then
        brew install zip
    else
        echo "Error: zip not found and cannot auto-install. Please install it manually."
        exit 1
    fi
fi

# Clean
rm -rf "$STAGING_DIR" "$DIST_DIR"
mkdir -p "$STAGING_DIR" "$DIST_DIR"

# Install ARM64 dependencies
echo ">>> Installing ARM64 dependencies..."
export PATH="$HOME/.local/bin:$PATH"
uv pip install \
    --python-platform aarch64-manylinux2014 \
    --python-version 3.13 \
    --target="$STAGING_DIR" \
    --only-binary=:all: \
    -r "$AGENT_DIR/requirements.txt"

# Copy agent source code
echo ">>> Copying agent source code..."
cp "$AGENT_DIR/main.py" "$STAGING_DIR/"

# Set correct permissions
echo ">>> Setting file permissions..."
find "$STAGING_DIR" -type f -exec chmod 644 {} +
find "$STAGING_DIR" -type d -exec chmod 755 {} +

# Create zip
echo ">>> Creating deployment_package.zip..."
cd "$STAGING_DIR"
zip -r "$DIST_DIR/deployment_package.zip" . -q

ZIP_SIZE=$(du -h "$DIST_DIR/deployment_package.zip" | cut -f1)
echo ""
echo "=========================================="
echo "  Build Complete!"
echo "  Output: dist/deployment_package.zip ($ZIP_SIZE)"
echo "=========================================="
