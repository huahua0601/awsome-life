# AgentCore Demo — Claude Opus 4.6 on AWS Bedrock AgentCore Runtime

通过 AWS CDK 部署一个运行在 Amazon Bedrock AgentCore Runtime 上的 AI Agent，使用 Strands Agents 框架与 Claude Opus 4.6 模型交互。采用 S3 直接代码部署方式（非 Docker）。

## 架构

```
┌──────────────┐     ┌──────────────────────────────────┐
│  invoke /    │     │   Amazon Bedrock AgentCore       │
│  load_test   │────▶│   Runtime (per-session microVM)  │
│  (boto3)     │◀────│                                  │
└──────────────┘     │   ┌───────────┐  ┌────────────┐  │
                     │   │  main.py  │─▶│ Claude     │  │
                     │   │  (Strands │  │ Opus 4.6   │  │
                     │   │   Agent)  │◀─│ (Bedrock)  │  │
                     │   └───────────┘  └────────────┘  │
                     └──────────────────────────────────┘
                                  ▲
                     ┌────────────┘
                     │  S3 (deployment_package.zip)
                     │  IAM Role / CloudWatch / X-Ray
                     └── AWS CDK 管理
```

## 项目结构

```
agentcore-demo/
├── app.py                  # CDK 入口
├── cdk.json                # CDK 配置（model_id, runtime_name）
├── requirements.txt        # CDK Python 依赖
├── stacks/
│   └── agentcore_stack.py  # CDK Stack（S3 + IAM + Runtime + Endpoint）
├── agent/
│   ├── main.py             # Agent 代码（Strands + Claude Opus 4.6）
│   └── requirements.txt    # Agent 依赖
├── build.sh                # 构建 ARM64 部署包
├── deploy.sh               # 一键构建 + CDK 部署
├── invoke_agent.py         # 调用 Agent（单次 / 交互式）
├── load_test.py            # 负载测试（累计产生指定费用）
└── dist/
    └── deployment_package.zip  # 构建产物
```

## 前置条件

- **AWS CLI** 已配置凭证（`aws configure`）
- **Node.js** >= 18（CDK CLI 依赖）
- **Python** >= 3.10
- **uv**（用于构建 ARM64 依赖包）
- **AWS CDK CLI**：`npm install -g aws-cdk`
- **模型访问**：在 [Amazon Bedrock 控制台](https://console.aws.amazon.com/bedrock/) 开通 `Claude Opus 4.6` 模型访问权限

安装 uv（如果未安装）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 部署

### 方式一：一键部署

```bash
cd agentcore-demo
./deploy.sh
```

### 方式二：手动分步部署

**1. 构建 ARM64 部署包**

```bash
./build.sh
```

这会使用 `uv pip` 下载 ARM64 架构的 Python 依赖，和 agent 源码一起打成 `dist/deployment_package.zip`。

**2. 安装 CDK 依赖并部署**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 首次部署需要 bootstrap
cdk bootstrap

# 部署
cdk deploy AgentCoreDemoStack --require-approval never
```

部署完成后会输出：

```
Outputs:
  AgentCoreDemoStack.RuntimeId = claude_opus_agent-XXXXXXXX
  AgentCoreDemoStack.RuntimeEndpointId = claude_opus_agent_endpoint
  AgentCoreDemoStack.RuntimeArn = arn:aws:bedrock-agentcore:us-west-2:XXXX:runtime/...
  AgentCoreDemoStack.CodeBucketName = agentcore-demo-code-XXXX-us-west-2
```

### 更新 Agent 代码

修改 `agent/main.py` 后，需要重新打包上传并更新 Runtime 版本：

```bash
# 重新构建
./build.sh

# 上传到 S3
aws s3 cp dist/deployment_package.zip s3://<CodeBucketName>/claude_opus_agent/deployment_package.zip

# 更新 Runtime（会创建新版本）
aws bedrock-agentcore-control update-agent-runtime \
  --agent-runtime-id <RuntimeId> \
  --agent-runtime-artifact '{
    "codeConfiguration": {
      "code": {"s3": {"bucket": "<CodeBucketName>", "prefix": "claude_opus_agent/deployment_package.zip"}},
      "runtime": "PYTHON_3_13",
      "entryPoint": ["main.py"]
    }
  }' \
  --network-configuration '{"networkMode": "PUBLIC"}' \
  --role-arn <RoleArn>

# 等待 READY 后更新 Endpoint 指向新版本
aws bedrock-agentcore-control update-agent-runtime-endpoint \
  --agent-runtime-id <RuntimeId> \
  --endpoint-name claude_opus_agent_endpoint \
  --agent-runtime-version <新版本号>
```

## 调用 Agent

先激活虚拟环境：

```bash
source .venv/bin/activate
```

### 单次调用

```bash
python invoke_agent.py "你好，请介绍一下你自己"
```

输出示例：

```
Prompt: 你好，请介绍一下你自己

Response:
你好！我是一个由 Claude Opus 4.6 驱动的 AI 智能助手...

--------------------------------------------------
  Model:         claude-opus-4-6-v1
  Input tokens:  55
  Output tokens: 54
  Total tokens:  109
  Pricing:       $5/M input, $25/M output
  Input cost:    $0.000275
  Output cost:   $0.001350
  Total cost:    $0.001625
--------------------------------------------------
```

### 交互式多轮对话

```bash
python invoke_agent.py
```

同一个 session 保持上下文，输入 `quit` 退出。

## 负载测试

`load_test.py` 循环调用 Agent，累计产生指定金额的 token 费用。单线程顺序调用，同时保持 AgentCore Runtime session 活跃以产生 Runtime 计算费用。

### 运行

```bash
source .venv/bin/activate

# 默认目标 $500
python load_test.py

# 自定义目标金额
python load_test.py --target-usd 200
```

执行后会要求输入 `YES` 确认（防止误操作），然后开始循环调用：

```
============================================================
  AgentCore 顺序调用测试
  Model: Claude Opus 4.6  |  $5/M input, $25/M output
  目标: $500  |  模式: 顺序调用 (单线程)
============================================================

  ⚠️  此测试将产生约 $500 的真实 AWS 费用!
  确认执行? (输入 YES 继续): YES

  [     1]  $   0.0135 / $500 (  0.0%)  |  tokens:        957  |  $/hr:    10.23  |  ETA: 48:52:11
  [     2]  $   0.0281 / $500 (  0.0%)  |  tokens:      1,914  |  $/hr:    11.87  |  ETA: 42:07:35
  ...
```

实时显示进度、累计 token、burn rate（$/hr）和预估剩余时间。

### 随时中断

按 **Ctrl+C** 可安全中断，会打印已产生的费用汇总。

## 费用说明

| 计费项 | 单价 |
|--------|------|
| Claude Opus 4.6 Input | $5 / 1M tokens |
| Claude Opus 4.6 Output | $25 / 1M tokens |
| AgentCore Runtime | 按 session 计算时间计费 |

## 清理资源

```bash
source .venv/bin/activate
cdk destroy AgentCoreDemoStack --force
```

这会删除 S3 Bucket、IAM Role、AgentCore Runtime 和 Endpoint 等所有资源。
