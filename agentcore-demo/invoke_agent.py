"""调用 AgentCore Runtime 上的 Claude Opus 4.6 Agent。

用法:
    python invoke_agent.py "你好，请介绍一下你自己"
    python invoke_agent.py                              # 进入交互式对话模式

环境变量 (可选):
    RUNTIME_ARN          覆盖自动检测的 Runtime ARN
    ENDPOINT_NAME        覆盖 endpoint 名称 (默认 claude_opus_agent_endpoint)
    AWS_DEFAULT_REGION   覆盖 region (默认 us-west-2)
"""

import json
import os
import sys
import time
import uuid

sys.stdout.reconfigure(line_buffering=True)

import boto3

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
ENDPOINT_NAME = os.environ.get("ENDPOINT_NAME", "claude_opus_agent_endpoint")
STACK_NAME = "AgentCoreDemoStack"

MAX_RETRIES = 5
RETRY_DELAY_SECS = 10


def get_runtime_arn():
    """从环境变量或 CloudFormation stack 输出获取 Runtime ARN。"""
    arn = os.environ.get("RUNTIME_ARN")
    if arn:
        return arn

    print("  正在从 CloudFormation 获取 Runtime ARN...", flush=True)
    cf = boto3.client("cloudformation", region_name=REGION)
    try:
        resp = cf.describe_stacks(StackName=STACK_NAME)
        for output in resp["Stacks"][0].get("Outputs", []):
            if output["OutputKey"] == "RuntimeArn":
                arn = output["OutputValue"]
                print(f"  Runtime ARN: {arn}", flush=True)
                return arn
    except Exception as e:
        pass

    print(f"  错误: 无法从 stack '{STACK_NAME}' 获取 RuntimeArn。请设置环境变量 RUNTIME_ARN。")
    sys.exit(1)


def invoke_agent(prompt: str, session_id: str | None = None, runtime_arn: str | None = None) -> tuple[dict, str]:
    """向 AgentCore Runtime 发送请求，返回完整响应 dict 和 session_id。"""
    if runtime_arn is None:
        runtime_arn = get_runtime_arn()
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    if session_id is None:
        session_id = str(uuid.uuid4())

    payload = json.dumps({"prompt": prompt}).encode("utf-8")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.invoke_agent_runtime(
                agentRuntimeArn=runtime_arn,
                qualifier=ENDPOINT_NAME,
                runtimeSessionId=session_id,
                contentType="application/json",
                accept="application/json",
                payload=payload,
            )
            break
        except client.exceptions.RuntimeClientError as e:
            error_msg = str(e)
            is_cold_start = "initialization time exceeded" in error_msg.lower()
            is_502 = "502" in error_msg
            if (is_cold_start or is_502) and attempt < MAX_RETRIES:
                print(f"  Runtime 启动中... 第 {attempt}/{MAX_RETRIES} 次重试 (等待 {RETRY_DELAY_SECS}s)")
                time.sleep(RETRY_DELAY_SECS)
            else:
                raise

    session_id = response.get("runtimeSessionId", session_id)
    raw = response["response"].read().decode("utf-8")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"result": raw}

    return data, session_id


def extract_text(data: dict) -> str:
    """从响应 data 中提取纯文本回复。"""
    result = data.get("result", data.get("output", ""))
    if isinstance(result, dict):
        content = result.get("content", [])
        texts = [c["text"] for c in content if "text" in c]
        return "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


def print_usage(data: dict):
    """打印 token 用量和费用信息。"""
    usage = data.get("usage")
    cost = data.get("cost")
    if not usage:
        return

    print("-" * 50)
    print(f"  Model:         {cost.get('model', 'N/A') if cost else 'N/A'}")
    print(f"  Input tokens:  {usage['input_tokens']:,}")
    print(f"  Output tokens: {usage['output_tokens']:,}")
    print(f"  Total tokens:  {usage['total_tokens']:,}")
    if cost:
        print(f"  Pricing:       {cost['pricing']}")
        print(f"  Input cost:    ${cost['input_cost_usd']:.6f}")
        print(f"  Output cost:   ${cost['output_cost_usd']:.6f}")
        print(f"  Total cost:    ${cost['total_cost_usd']:.6f}")
    print("-" * 50)


def interactive_mode(runtime_arn=None):
    """交互式多轮对话模式。"""
    if runtime_arn is None:
        runtime_arn = get_runtime_arn()
    print("=" * 50)
    print("  AgentCore Claude Opus 4.6 交互式对话")
    print("  输入 'quit' 或 'exit' 退出")
    print("=" * 50)
    print()

    session_id = str(uuid.uuid4())
    print(f"Session: {session_id}\n")

    while True:
        try:
            prompt = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not prompt:
            continue
        if prompt.lower() in ("quit", "exit"):
            print("再见！")
            break

        try:
            data, session_id = invoke_agent(prompt, session_id, runtime_arn=runtime_arn)
            text = extract_text(data)
            print(f"\nAgent: {text}\n")
            print_usage(data)
        except Exception as e:
            print(f"\n错误: {e}\n")


def main():
    runtime_arn = get_runtime_arn()
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        print(f"Prompt: {prompt}\n")
        data, session_id = invoke_agent(prompt, runtime_arn=runtime_arn)
        text = extract_text(data)
        print(f"Response:\n{text}\n")
        print_usage(data)
        print(f"Session ID: {session_id}")
    else:
        interactive_mode(runtime_arn)


if __name__ == "__main__":
    main()
