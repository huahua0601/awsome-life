#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$SCRIPT_DIR/agent"
DIST_DIR="$SCRIPT_DIR/dist"
STAGING_DIR="$SCRIPT_DIR/.build/deployment_package"

echo "=========================================="
echo "  Building ARM64 deployment package"
echo "=========================================="

# Clean
rm -rf "$STAGING_DIR" "$DIST_DIR"
mkdir -p "$STAGING_DIR" "$DIST_DIR"

# Install ARM64 dependencies using uv pip
echo ">>> Installing ARM64 dependencies..."
if command -v uv >/dev/null 2>&1; then
    uv pip install \
        --python-platform aarch64-manylinux2014 \
        --python-version 3.13 \
        --target="$STAGING_DIR" \
        --only-binary=:all: \
        -r "$AGENT_DIR/requirements.txt"
else
    echo "Error: uv is required. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

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
