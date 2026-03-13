#!/usr/bin/env bash
set -euo pipefail

###############################################################################
#  Kiro 批量开通脚本 — Shell 入口
#  自动检查 Python/boto3 依赖后调用 batch_enable_kiro.py
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} 需要 Python 3，请先安装"
    exit 1
fi

if ! python3 -c "import boto3" 2>/dev/null; then
    echo -e "${YELLOW}[INFO]${NC}  安装 boto3..."
    pip3 install boto3 --quiet 2>/dev/null || pip install boto3 --quiet
fi

if ! command -v aws >/dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} 需要 AWS CLI，请先安装: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html"
    exit 1
fi

exec python3 "$SCRIPT_DIR/batch_enable_kiro.py" "$@"
