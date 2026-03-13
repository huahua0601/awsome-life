#!/usr/bin/env python3
"""
Kiro 批量开通脚本

从邮件列表文件中读取邮箱地址，通过 AWS API 批量开通 Kiro 订阅。

工作流程:
  1. 在 IAM Identity Center 中查找/创建用户
  2. 通过 AmazonQDeveloperService.CreateAssignment API 为用户开通 Kiro 订阅
  3. 同时将用户分配到 KiroProfile SSO 应用 (确保 SSO 登录)

用法:
  python3 batch_enable_kiro.py emails.txt [OPTIONS]
"""

import argparse
import json
import re
import sys
import time

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import ClientError, NoCredentialsError

# ---------------------------------------------------------------------------
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"

KIRO_PROFILE_PROVIDER = "codewhisperer"
CW_ENDPOINT = "https://codewhisperer.{region}.amazonaws.com/"

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def log_info(msg):
    print(f"{CYAN}[INFO]{NC}  {msg}")


def log_ok(msg):
    print(f"{GREEN}[OK]{NC}    {msg}")


def log_warn(msg):
    print(f"{YELLOW}[WARN]{NC}  {msg}")


def log_error(msg):
    print(f"{RED}[ERROR]{NC} {msg}")


def log_section(msg):
    print(f"\n{BOLD}=== {msg} ==={NC}")


def die(msg):
    log_error(msg)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 读取邮件列表
# ---------------------------------------------------------------------------
def read_emails(filepath: str) -> list[str]:
    emails = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            if EMAIL_RE.match(line):
                emails.append(line)
            else:
                log_warn(f"跳过无效邮箱: {line}")
    if not emails:
        die("文件中没有有效的邮箱地址")
    return emails


# ---------------------------------------------------------------------------
# Identity Center helpers
# ---------------------------------------------------------------------------
def get_sso_instance(sso_admin):
    resp = sso_admin.list_instances()
    instances = resp.get("Instances", [])
    if not instances:
        die("未找到 IAM Identity Center 实例")
    inst = instances[0]
    return inst["InstanceArn"], inst["IdentityStoreId"]


def find_kiro_profile_app(sso_admin, instance_arn: str) -> str | None:
    """查找 KiroProfile-<region> SSO 应用 (provider = codewhisperer)"""
    paginator = sso_admin.get_paginator("list_applications")
    for page in paginator.paginate(InstanceArn=instance_arn):
        for app in page.get("Applications", []):
            provider = app.get("ApplicationProviderArn", "")
            name = app.get("Name", "")
            if KIRO_PROFILE_PROVIDER in provider and name.startswith("KiroProfile-"):
                return app["ApplicationArn"]
    return None


def get_all_kiro_app_arns(sso_admin, instance_arn: str) -> list[str]:
    arns = []
    paginator = sso_admin.get_paginator("list_applications")
    for page in paginator.paginate(InstanceArn=instance_arn):
        for app in page.get("Applications", []):
            if KIRO_PROFILE_PROVIDER in app.get("ApplicationProviderArn", ""):
                arns.append(app["ApplicationArn"])
    return arns


def find_user_by_email(identitystore, identity_store_id: str, email: str) -> str | None:
    try:
        resp = identitystore.list_users(
            IdentityStoreId=identity_store_id,
            Filters=[{"AttributePath": "UserName", "AttributeValue": email}],
        )
        users = resp.get("Users", [])
        if users:
            return users[0]["UserId"]
    except ClientError:
        pass
    return None


def create_user(identitystore, identity_store_id: str, email: str) -> str | None:
    username = email.split("@")[0]
    try:
        resp = identitystore.create_user(
            IdentityStoreId=identity_store_id,
            UserName=email,
            DisplayName=username,
            Name={"GivenName": username, "FamilyName": "User"},
            Emails=[{"Value": email, "Type": "work", "Primary": True}],
        )
        return resp["UserId"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            return find_user_by_email(identitystore, identity_store_id, email)
        log_error(f"创建用户失败 ({email}): {e}")
        return None


# ---------------------------------------------------------------------------
# Kiro 订阅 (通过内部 API)
# ---------------------------------------------------------------------------
def create_kiro_assignment(credentials, region: str, user_id: str) -> tuple[bool, str]:
    """通过 AmazonQDeveloperService.CreateAssignment 创建 Kiro 订阅

    这是 AWS 内部 API，通过 codewhisperer endpoint 调用，签名服务为 'q'。
    """
    endpoint = CW_ENDPOINT.format(region=region)
    payload = json.dumps({"principalId": user_id, "principalType": "USER"})

    request = AWSRequest(
        method="POST",
        url=endpoint,
        data=payload,
        headers={
            "Content-Type": "application/x-amz-json-1.0",
            "X-Amz-Target": "AmazonQDeveloperService.CreateAssignment",
        },
    )
    SigV4Auth(credentials, "q", region).add_auth(request)

    response = requests.post(
        request.url, headers=dict(request.headers), data=request.body, timeout=15
    )

    if response.status_code == 200:
        return True, "OK"

    body = response.text
    if "ConflictException" in body or "already exists" in body.lower():
        return True, "已存在"

    return False, f"HTTP {response.status_code}: {body[:200]}"


def assign_user_to_sso_app(sso_admin, app_arn: str, user_id: str) -> bool:
    try:
        sso_admin.create_application_assignment(
            ApplicationArn=app_arn, PrincipalId=user_id, PrincipalType="USER"
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            return True
        return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Kiro 批量开通脚本 — 从邮件列表批量开通 Kiro 订阅"
    )
    parser.add_argument("emails_file", help="包含邮箱地址的文件 (每行一个)")
    parser.add_argument(
        "--region", default="us-east-1", help="AWS 区域 (默认: us-east-1)"
    )
    parser.add_argument("--profile", default=None, help="AWS CLI profile 名称")
    parser.add_argument(
        "--dry-run", action="store_true", help="仅检查，不执行实际操作"
    )
    parser.add_argument(
        "--create-users",
        action="store_true",
        help="若 Identity Center 中不存在该用户则自动创建",
    )
    args = parser.parse_args()

    print()
    print(f"{BOLD}==========================================")
    print(f"  Kiro 批量开通脚本")
    print(f"=========================================={NC}")

    # --- 验证 AWS 凭证 ---
    log_section("验证 AWS 凭证")
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        account_id = identity["Account"]
        log_ok(f"AWS Account: {account_id}")
    except (NoCredentialsError, ClientError) as e:
        die(f"AWS 凭证未配置或无效: {e}")

    # --- 读取邮件列表 ---
    log_section("读取邮件列表")
    emails = read_emails(args.emails_file)
    log_info(f"从 {args.emails_file} 中读取到 {len(emails)} 个邮箱地址")

    # --- 获取 Identity Center 信息 ---
    log_section("获取 IAM Identity Center 信息")
    sso_admin = session.client("sso-admin")
    identitystore = session.client("identitystore")
    instance_arn, identity_store_id = get_sso_instance(sso_admin)
    log_ok(f"Instance ARN:     {instance_arn}")
    log_ok(f"Identity Store:   {identity_store_id}")

    # --- 检查 Kiro Profile ---
    log_section("检查 Kiro Profile")
    kiro_app_arn = find_kiro_profile_app(sso_admin, instance_arn)
    if kiro_app_arn:
        log_ok(f"Kiro Profile 应用: {kiro_app_arn}")
    else:
        die(
            "未找到 Kiro Profile。请先在 AWS 控制台创建:\n"
            "  1. 打开 https://console.aws.amazon.com/kiro/\n"
            "  2. 点击 'Sign up for Kiro' 创建 Profile"
        )

    all_kiro_arns = get_all_kiro_app_arns(sso_admin, instance_arn)
    credentials = session.get_credentials()

    # --- 配置摘要 ---
    log_section("配置摘要")
    print(f"  账号:       {account_id}")
    print(f"  区域:       {args.region}")
    print(f"  用户数量:   {len(emails)}")
    print(f"  自动创建:   {args.create_users}")
    print(f"  Dry Run:    {args.dry_run}")
    print()

    if not args.dry_run:
        print(f"{YELLOW}即将为 {len(emails)} 个用户开通 Kiro 订阅{NC}")
        confirm = input("确认执行? (输入 YES 继续): ").strip()
        if confirm != "YES":
            print("已取消")
            return

    # --- 处理用户 ---
    log_section("处理用户")
    success = 0
    failed = 0
    skipped = 0
    created = 0
    failed_emails = []

    for email in emails:
        print(f"\n--- 处理: {BOLD}{email}{NC}")

        # 查找/创建用户
        user_id = find_user_by_email(identitystore, identity_store_id, email)
        if not user_id:
            if args.create_users and not args.dry_run:
                log_warn("用户不存在，正在创建...")
                user_id = create_user(identitystore, identity_store_id, email)
                if not user_id:
                    failed += 1
                    failed_emails.append(f"{email} (创建失败)")
                    continue
                log_ok(f"用户已创建: {user_id}")
                created += 1
            elif args.dry_run:
                log_warn(f"用户不存在: {email}")
                skipped += 1
                continue
            else:
                log_error(f"用户不存在: {email} (使用 --create-users 自动创建)")
                failed += 1
                failed_emails.append(f"{email} (用户不存在)")
                continue
        else:
            log_ok(f"找到用户: {user_id}")

        if args.dry_run:
            log_info(f"[DRY RUN] 将为用户开通 Kiro: {email} ({user_id})")
            skipped += 1
            continue

        # 步骤 1: 通过内部 API 创建 Kiro 订阅
        ok, msg = create_kiro_assignment(credentials, args.region, user_id)
        if ok:
            log_ok(f"Kiro 订阅已创建: {email} ({msg})")
        else:
            log_warn(f"Kiro 内部 API 调用失败: {msg}")
            log_info("回退到 SSO 应用分配方式...")

        # 步骤 2: 分配到 KiroProfile SSO 应用 (确保 SSO 登录权限)
        sso_ok = True
        for arn in all_kiro_arns:
            if not assign_user_to_sso_app(sso_admin, arn, user_id):
                sso_ok = False

        if ok:
            log_ok(f"Kiro 已开通: {email}")
            success += 1
        elif sso_ok:
            log_warn(f"已添加 SSO 应用权限，但可能需要在 Kiro 控制台手动分配订阅: {email}")
            success += 1
        else:
            log_error(f"开通失败: {email}")
            failed += 1
            failed_emails.append(f"{email} (订阅失败)")

        time.sleep(0.5)

    # --- 结果 ---
    log_section("执行结果")
    print(f"  总数:     {len(emails)}")
    print(f"  {GREEN}成功:     {success}{NC}")
    if created > 0:
        print(f"  {CYAN}新建用户: {created}{NC}")
    if skipped > 0:
        print(f"  {YELLOW}跳过:     {skipped}{NC}")
    if failed > 0:
        print(f"  {RED}失败:     {failed}{NC}")

    if failed_emails:
        print()
        log_warn("失败列表:")
        for item in failed_emails:
            print(f"  - {item}")
        fail_file = args.emails_file.replace(".txt", "_failed.txt")
        if fail_file == args.emails_file:
            fail_file += ".failed"
        with open(fail_file, "w") as f:
            f.write("\n".join(failed_emails) + "\n")
        log_info(f"失败列表已保存到: {fail_file}")

    print()
    if args.dry_run:
        print(f"{YELLOW}[DRY RUN] 未执行实际操作。{NC}")
    elif failed == 0 and success > 0:
        print(f"{GREEN}{BOLD}处理完成!{NC}")
        print()
        log_info("如果用户未在 Kiro 控制台的用户列表中显示，请在控制台手动完成最后一步:")
        print(f"  1. 打开 {CYAN}https://us-east-1.console.aws.amazon.com/kiro/users{NC}")
        print(f"  2. 点击 {BOLD}Add user{NC} → 搜索用户名 → 选择 Plan → 点击 {BOLD}Assign{NC}")
        print(f"  3. 用户将在 24 小时内收到 Kiro 开通邮件")
    print()


if __name__ == "__main__":
    main()
