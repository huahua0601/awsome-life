"""顺序调用 AgentCore Agent，累计产生约 $500 token 费用。

同时 AgentCore Runtime 按 session 计算时间收费，慢慢调用也会产生 Runtime 费用。
参考: https://github.com/awslabs/amazon-bedrock-agentcore-samples

用法:
    python load_test.py                     # 默认 $500
    python load_test.py --target-usd 200    # 自定义金额

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

INPUT_PRICE_PER_TOKEN = 5.0 / 1_000_000
OUTPUT_PRICE_PER_TOKEN = 25.0 / 1_000_000

PROMPTS = [
    "请详细解释量子计算的基本原理，包括量子比特、叠加态、量子纠缠和量子门的概念，并举例说明量子算法的应用场景。",
    "请用 Python 实现一个完整的 LRU Cache，包含 get、put 方法，支持并发访问，附上详细注释和使用示例。",
    "请详细比较微服务架构和单体架构的优缺点，从性能、可维护性、部署复杂度、团队协作等多个维度分析，并给出选型建议。",
    "请详细解释 Transformer 架构的工作原理，包括 self-attention、multi-head attention、positional encoding 的数学推导。",
    "请用 Python 实现一个红黑树，包含插入、删除、查找操作，每个方法附上详细注释，并写测试用例。",
    "请详细介绍 Kubernetes 的核心概念和架构，包括 Pod、Service、Deployment、StatefulSet、Ingress 的作用和使用场景。",
    "请写一篇关于分布式系统中一致性协议的详细文章，涵盖 Paxos、Raft、ZAB 协议的对比分析。",
    "请详细解释 TCP/IP 协议栈的四层模型，每层的核心协议及其工作原理，包括三次握手、四次挥手、拥塞控制等机制。",
    "请用 Python 从零实现一个简单的神经网络框架，支持全连接层、激活函数、反向传播和梯度下降，附上完整的训练示例。",
    "请详细分析 Amazon DynamoDB 的架构设计，包括分区策略、一致性模型、GSI/LSI 索引、容量模式的对比。",
    "请详细解释 OAuth 2.0 和 OpenID Connect 的工作流程，包括 Authorization Code Flow、PKCE、Refresh Token。",
    "请用 Go 语言实现一个高性能的 HTTP 反向代理服务器，支持负载均衡、健康检查、限流和日志记录，附上详细注释。",
    "请写一篇关于大语言模型训练流程的详细技术文章，涵盖数据预处理、Tokenization、预训练、SFT、RLHF 各阶段。",
    "请详细对比 AWS、Azure 和 GCP 的核心服务，从计算、存储、数据库、AI/ML、网络和安全等方面分析各自优势。",
    "请用 Python 实现一个完整的 B+ 树索引结构，支持插入、删除、范围查询操作，附上时间复杂度分析和单元测试。",
]


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


def invoke_once(client, prompt, runtime_arn, session_id=None):
    """调用一次 Agent，返回 (data_dict, runtime_session_id)。"""
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
                print(f"    (Runtime 启动中... 重试 {attempt}/{MAX_RETRIES}, 等待 {wait}s)")
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
        print(f"  Session '{session_id}' 已停止，microVM 资源已释放")
    except Exception as e:
        print(f"  停止 session 失败 (可忽略): {e}")


def warmup(client, runtime_arn):
    """预热 Runtime，等待 microVM 就绪后再正式开始。"""
    print("  预热中 (首次调用触发 microVM 启动)...")
    data, session_id = invoke_once(client, "Hello, respond with just 'OK'.", runtime_arn)
    print(f"  预热成功! Session: {session_id}")
    return session_id


def main():
    target_usd = 500.0
    if "--target-usd" in sys.argv:
        target_usd = float(sys.argv[sys.argv.index("--target-usd") + 1])

    print("=" * 64)
    print("  AgentCore 顺序调用测试")
    print("  Model: Claude Opus 4.6  |  $5/M input, $25/M output")
    print(f"  目标: ${target_usd:,.0f}  |  模式: 顺序调用 (单线程)")
    print("=" * 64)
    print(f"\n  ⚠️  此测试将产生约 ${target_usd:,.0f} 的真实 AWS 费用!")
    confirm = input("  确认执行? (输入 YES 继续): ").strip()
    if confirm != "YES":
        print("  已取消。")
        return

    runtime_arn = get_runtime_arn()
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    session_id = warmup(client, runtime_arn)

    total_input = 0
    total_output = 0
    total_cost = 0.0
    call_count = 0
    error_count = 0
    start_time = time.time()

    print(f"\n  开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Session: {session_id}\n")

    try:
        while total_cost < target_usd:
            prompt = PROMPTS[call_count % len(PROMPTS)]
            call_count += 1

            try:
                data, new_sid = invoke_once(client, prompt, runtime_arn, session_id)
                if new_sid:
                    session_id = new_sid

                usage = data.get("usage", {})
                cost_info = data.get("cost", {})
                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
                usd = cost_info.get("total_cost_usd", 0)

                total_input += inp
                total_output += out
                total_cost += usd

            except Exception as e:
                error_count += 1
                print(f"  [{call_count:>6,}] 错误: {e}")
                time.sleep(10)
                continue

            elapsed = time.time() - start_time
            pct = total_cost / target_usd * 100
            rate = total_cost / elapsed * 3600 if elapsed > 0 else 0
            remaining = target_usd - total_cost
            eta_secs = remaining / (total_cost / elapsed) if total_cost > 0 else 0
            eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_secs))

            print(
                f"  [{call_count:>6,}]"
                f"  ${total_cost:>10,.4f} / ${target_usd:,.0f} ({pct:>5.1f}%)"
                f"  |  tokens: {total_input + total_output:>10,}"
                f"  |  $/hr: {rate:>8,.2f}"
                f"  |  ETA: {eta_str}"
            )

    except KeyboardInterrupt:
        print("\n\n  ⚠️  用户中断 (Ctrl+C)")

    elapsed = time.time() - start_time
    elapsed_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))

    print()
    print("=" * 64)
    print("  测试结果汇总")
    print("=" * 64)
    print(f"  调用次数:       {call_count:,} (失败 {error_count})")
    print(f"  总耗时:         {elapsed_str}")
    print(f"  Input tokens:   {total_input:,}")
    print(f"  Output tokens:  {total_output:,}")
    print(f"  Total tokens:   {total_input + total_output:,}")
    print()
    print(f"  Input cost:     ${total_input * INPUT_PRICE_PER_TOKEN:,.4f}")
    print(f"  Output cost:    ${total_output * OUTPUT_PRICE_PER_TOKEN:,.4f}")
    print(f"  Total cost:     ${total_cost:,.4f}")
    if elapsed > 0:
        print(f"  平均每次:       ${total_cost / max(call_count - error_count, 1):,.4f}")
        print(f"  Burn rate:      ${total_cost / elapsed * 3600:,.2f}/hr")
    print("=" * 64)

    print("\n  正在停止 session 释放资源...")
    stop_session(client, runtime_arn, session_id)


if __name__ == "__main__":
    main()
