#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  AgentCore Demo - Build & Deploy"
echo "=========================================="

# --- Privilege escalation helper (sudo / doas / root) ----------------------
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

# --- Auto-install prerequisites -------------------------------------------

# Node.js & npm
if ! command -v node >/dev/null 2>&1; then
    echo ">>> Installing Node.js..."
    if command -v pkg >/dev/null 2>&1; then
        _sudo pkg install -y node npm
    elif command -v apt-get >/dev/null 2>&1; then
        _sudo apt-get update -qq && _sudo apt-get install -y -qq nodejs npm
    elif command -v yum >/dev/null 2>&1; then
        _sudo yum install -y nodejs npm
    elif command -v dnf >/dev/null 2>&1; then
        _sudo dnf install -y nodejs npm
    elif command -v brew >/dev/null 2>&1; then
        brew install node
    else
        curl -fsSL https://fnm.vercel.app/install | bash
        export PATH="$HOME/.local/share/fnm:$PATH"
        eval "$(fnm env)"
        fnm install --lts
    fi
fi

# AWS CLI
if ! command -v aws >/dev/null 2>&1; then
    echo ">>> Installing AWS CLI..."
    if command -v pip3 >/dev/null 2>&1; then
        pip3 install awscli --quiet
    elif command -v pip >/dev/null 2>&1; then
        pip install awscli --quiet
    else
        curl "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscliv2.zip
        unzip -qo /tmp/awscliv2.zip -d /tmp && _sudo /tmp/aws/install && rm -rf /tmp/aws /tmp/awscliv2.zip
    fi
fi

# AWS CDK
if ! command -v cdk >/dev/null 2>&1; then
    echo ">>> Installing AWS CDK..."
    npm install -g aws-cdk
fi

# uv
if ! command -v uv >/dev/null 2>&1; then
    echo ">>> Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# zip
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
    fi
fi

# Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo ">>> Installing Python 3..."
    if command -v pkg >/dev/null 2>&1; then
        _sudo pkg install -y python3
    elif command -v apt-get >/dev/null 2>&1; then
        _sudo apt-get install -y -qq python3 python3-venv
    elif command -v yum >/dev/null 2>&1; then
        _sudo yum install -y python3
    elif command -v dnf >/dev/null 2>&1; then
        _sudo dnf install -y python3
    elif command -v brew >/dev/null 2>&1; then
        brew install python
    fi
fi

# --- Verify AWS credentials -----------------------------------------------
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-west-2}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || {
    echo "Error: AWS credentials not configured. Run: aws configure"
    exit 1
}

echo ""
echo "Account:  $ACCOUNT_ID"
echo "Region:   $AWS_DEFAULT_REGION"
echo "Model:    global.anthropic.claude-opus-4-6-v1"
echo "Deploy:   S3 direct code"
echo ""

# --- Step 1: Build deployment package -------------------------------------
echo ">>> Step 1: Building ARM64 deployment package..."
export PATH="$HOME/.local/bin:$PATH"
bash "$SCRIPT_DIR/build.sh"

# --- Step 2: Set up CDK virtual environment --------------------------------
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo ">>> Creating Python virtual environment for CDK..."
    python3 -m venv "$SCRIPT_DIR/.venv"
fi
source "$SCRIPT_DIR/.venv/bin/activate"
pip install -r "$SCRIPT_DIR/requirements.txt" -q

# --- Step 3: Bootstrap CDK ------------------------------------------------
echo ">>> Step 2: Bootstrapping CDK..."
cdk bootstrap aws://$ACCOUNT_ID/$AWS_DEFAULT_REGION

# --- Step 4: Deploy -------------------------------------------------------
echo ">>> Step 3: Deploying AgentCore stack..."
cdk deploy AgentCoreDemoStack --require-approval never

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "Test via AgentCore console:"
echo "  https://${AWS_DEFAULT_REGION}.console.aws.amazon.com/bedrock-agentcore/agents"
echo ""
echo "Or invoke via CLI:"
echo '  RUNTIME_ID=$(aws cloudformation describe-stacks \'
echo '    --stack-name AgentCoreDemoStack \'
echo "    --query 'Stacks[0].Outputs[?OutputKey==\`RuntimeId\`].OutputValue' \\"
echo '    --output text)'
echo ""
echo '  aws bedrock-agentcore invoke-runtime-endpoint \'
echo '    --runtime-id $RUNTIME_ID \'
echo '    --endpoint-name claude_opus_agent_endpoint \'
echo "    --payload '{\"prompt\": \"你好，请介绍一下你自己\"}'"
