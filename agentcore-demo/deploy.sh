#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  AgentCore Demo - Build & Deploy"
echo "=========================================="

# Check prerequisites
command -v aws >/dev/null 2>&1 || { echo "Error: aws CLI not found"; exit 1; }
command -v cdk >/dev/null 2>&1 || { echo "Error: cdk not found. Run: npm install -g aws-cdk"; exit 1; }
command -v uv >/dev/null 2>&1  || { echo "Error: uv not found. Run: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }

export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-west-2}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo ""
echo "Account:  $ACCOUNT_ID"
echo "Region:   $AWS_DEFAULT_REGION"
echo "Model:    global.anthropic.claude-opus-4-6-v1"
echo "Deploy:   S3 direct code"
echo ""

# Step 1: Build deployment package
echo ">>> Step 1: Building ARM64 deployment package..."
bash "$SCRIPT_DIR/build.sh"

# Step 2: Set up CDK virtual environment
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo ">>> Creating Python virtual environment for CDK..."
    python3 -m venv "$SCRIPT_DIR/.venv"
fi
source "$SCRIPT_DIR/.venv/bin/activate"
pip install -r "$SCRIPT_DIR/requirements.txt" -q

# Step 3: Bootstrap CDK
echo ">>> Step 2: Bootstrapping CDK..."
cdk bootstrap aws://$ACCOUNT_ID/$AWS_DEFAULT_REGION

# Step 4: Deploy
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
