#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$SCRIPT_DIR/agent"
DIST_DIR="$SCRIPT_DIR/dist"
STAGING_DIR="$SCRIPT_DIR/.build/deployment_package"

echo "=========================================="
echo "  Building ARM64 deployment package"
echo "=========================================="

# Try to install uv if missing (optional — falls back to pip)
if ! command -v uv >/dev/null 2>&1; then
    echo ">>> Attempting to install uv..."
    if curl -LsSf https://astral.sh/uv/install.sh 2>/dev/null | sh 2>/dev/null; then
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo "    uv not available for this platform — will use pip"
    fi
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

# Install ARM64 dependencies (uv preferred, pip as fallback)
echo ">>> Installing ARM64 dependencies..."
export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
    uv pip install \
        --python-platform aarch64-manylinux2014 \
        --python-version 3.13 \
        --target="$STAGING_DIR" \
        --only-binary=:all: \
        -r "$AGENT_DIR/requirements.txt"
else
    echo "    (using pip fallback for cross-platform install)"
    PIP="python3 -m pip"
    # Ensure pip module is available
    if ! python3 -m pip --version >/dev/null 2>&1; then
        echo ">>> Installing pip..."
        python3 -m ensurepip --default-pip 2>/dev/null || {
            curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
            python3 /tmp/get-pip.py --quiet && rm -f /tmp/get-pip.py
        }
    fi
    $PIP install \
        --platform manylinux2014_aarch64 \
        --python-version 3.13 \
        --implementation cp \
        --only-binary=:all: \
        --target="$STAGING_DIR" \
        --no-deps \
        -r "$AGENT_DIR/requirements.txt"
    $PIP install \
        --platform manylinux2014_aarch64 \
        --python-version 3.13 \
        --implementation cp \
        --only-binary=:all: \
        --target="$STAGING_DIR" \
        --no-deps \
        pydantic pydantic-core typing-extensions annotated-types \
        boto3 botocore s3transfer jmespath urllib3 python-dateutil six
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
