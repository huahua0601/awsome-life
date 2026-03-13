"""调用 AgentCore Runtime 上的 Claude Opus 4.6 Agent。

参考: https://github.com/awslabs/amazon-bedrock-agentcore-samples

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

sys.stdout.reconfigure(line_buffering=True)

import boto3

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
ENDPOINT_NAME = os.environ.get("ENDPOINT_NAME", "claude_opus_agent_endpoint")
STACK_NAME = "AgentCoreDemoStack"

MAX_RETRIES = 8
RETRY_DELAY_SECS = 15


def get_runtime_arn():
    """从环境变量或 CloudFormation stack 输出获取 Runtime ARN。"""
    arn = os.environ.get("RUNTIME_ARN")
    if arn:
        return arn

    print("  正在从 CloudFormation 获取 Runtime ARN...")
    cf = boto3.client("cloudformation", region_name=REGION)
    try:
        resp = cf.describe_stacks(StackName=STACK_NAME)
        for output in resp["Stacks"][0].get("Outputs", []):
            if output["OutputKey"] == "RuntimeArn":
                arn = output["OutputValue"]
                print(f"  Runtime ARN: {arn}")
                return arn
    except Exception:
        pass

    print(f"  错误: 无法从 stack '{STACK_NAME}' 获取 RuntimeArn。请设置环境变量 RUNTIME_ARN。")
    sys.exit(1)


def read_response(resp):
    """从 invoke_agent_runtime 响应中读取 payload (兼容 EventStream 和普通响应)。"""
    content_type = resp.get("contentType", "")

    if "text/event-stream" in content_type:
        parts = []
        for line in resp["response"].iter_lines(chunk_size=1):
            if line:
                decoded = line.decode("utf-8")
                if decoded.startswith("data: "):
                    parts.append(decoded[6:])
        raw = "".join(parts)
    else:
        try:
            events = []
            for event in resp.get("response", []):
                if isinstance(event, bytes):
                    events.append(event.decode("utf-8"))
                else:
                    events.append(str(event))
            raw = "".join(events)
        except Exception:
            raw = resp["response"].read().decode("utf-8")

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"result": raw}


def invoke_agent(client, prompt, runtime_arn, session_id=None):
    """向 AgentCore Runtime 发送请求，返回 (data_dict, runtime_session_id)。"""
    kwargs = {
        "agentRuntimeArn": runtime_arn,
        "qualifier": ENDPOINT_NAME,
        "payload": json.dumps({"prompt": prompt}),
    }
    if session_id:
        kwargs["runtimeSessionId"] = session_id

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.invoke_agent_runtime(**kwargs)
            runtime_session_id = resp.get("runtimeSessionId", session_id)
            data = read_response(resp)
            return data, runtime_session_id
        except (client.exceptions.RuntimeClientError, Exception) as e:
            msg = str(e)
            is_retryable = any(s in msg.lower() for s in [
                "initialization time exceeded", "502", "503",
                "throttl", "timeout", "service unavailable",
            ])
            if is_retryable and attempt < MAX_RETRIES:
                wait = RETRY_DELAY_SECS * attempt
                print(f"  Runtime 启动中... 第 {attempt}/{MAX_RETRIES} 次重试 (等待 {wait}s)")
                time.sleep(wait)
            else:
                raise

    return {}, session_id


def stop_session(client, runtime_arn, session_id):
    """停止 runtime session 以释放 microVM 资源。"""
    if not session_id:
        return
    try:
        client.stop_runtime_session(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=session_id,
            qualifier=ENDPOINT_NAME,
        )
        print(f"  Session 已停止: {session_id}")
    except Exception as e:
        print(f"  停止 session 失败 (可忽略): {e}")


def extract_text(data):
    """从响应 data 中提取纯文本回复。"""
    result = data.get("result", data.get("output", ""))
    if isinstance(result, dict):
        content = result.get("content", [])
        texts = [c["text"] for c in content if "text" in c]
        return "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


def print_usage(data):
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


def interactive_mode(client, runtime_arn):
    """交互式多轮对话模式。"""
    print("=" * 50)
    print("  AgentCore Claude Opus 4.6 交互式对话")
    print("  输入 'quit' 或 'exit' 退出")
    print("=" * 50)
    print()

    session_id = None
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
            data, session_id = invoke_agent(client, prompt, runtime_arn, session_id)
            text = extract_text(data)
            print(f"\nAgent: {text}\n")
            print_usage(data)
        except Exception as e:
            print(f"\n错误: {e}\n")

    stop_session(client, runtime_arn, session_id)


def main():
    runtime_arn = get_runtime_arn()
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        print(f"Prompt: {prompt}\n")
        data, session_id = invoke_agent(client, prompt, runtime_arn)
        text = extract_text(data)
        print(f"Response:\n{text}\n")
        print_usage(data)
        print(f"Session ID: {session_id}")
        stop_session(client, runtime_arn, session_id)
    else:
        interactive_mode(client, runtime_arn)


if __name__ == "__main__":
    main()
