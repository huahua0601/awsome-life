#!/usr/bin/env python3
"""
QuickSight 批量开通脚本

从邮件列表文件中读取邮箱地址，通过 QuickSight register-user API 批量注册用户。

用法:
  python3 batch_register_quicksight.py emails.txt [OPTIONS]
"""

import argparse
import re
import sys
import time

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

VALID_ROLES = ["READER", "AUTHOR", "ADMIN", "READER_PRO", "AUTHOR_PRO", "ADMIN_PRO"]
VALID_IDENTITY_TYPES = ["QUICKSIGHT", "IAM", "IAM_IDENTITY_CENTER"]


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


def check_user_exists(qs, account_id: str, namespace: str, email: str) -> bool:
    """检查用户是否已在 QuickSight 中注册"""
    try:
        paginator = qs.get_paginator("list_users")
        for page in paginator.paginate(AwsAccountId=account_id, Namespace=namespace):
            for user in page.get("UserList", []):
                if user.get("Email", "").lower() == email.lower():
                    return True
    except ClientError:
        pass
    return False


def register_user(
    qs,
    account_id: str,
    namespace: str,
    email: str,
    role: str,
    identity_type: str,
) -> tuple[bool, str]:
    """注册 QuickSight 用户"""
    username = email.split("@")[0]

    kwargs = {
        "IdentityType": identity_type,
        "Email": email,
        "UserRole": role,
        "AwsAccountId": account_id,
        "Namespace": namespace,
    }

    if identity_type == "QUICKSIGHT":
        kwargs["UserName"] = email

    try:
        resp = qs.register_user(**kwargs)
        user = resp.get("User", {})
        invitation_url = resp.get("UserInvitationUrl", "")
        status = resp.get("Status", 0)

        if status == 201:
            return True, invitation_url or "已注册"
        return True, f"Status={status}"
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        if code == "ResourceExistsException":
            return True, "用户已存在"
        if "already exists" in msg.lower():
            return True, "用户已存在"
        return False, f"{code}: {msg}"


def main():
    parser = argparse.ArgumentParser(
        description="QuickSight 批量开通脚本 — 从邮件列表批量注册 QuickSight 用户"
    )
    parser.add_argument("emails_file", help="包含邮箱地址的文件 (每行一个)")
    parser.add_argument(
        "--role",
        choices=VALID_ROLES,
        default="READER",
        help="QuickSight 用户角色 (默认: READER)",
    )
    parser.add_argument(
        "--identity-type",
        choices=VALID_IDENTITY_TYPES,
        default="QUICKSIGHT",
        help="身份类型 (默认: QUICKSIGHT)",
    )
    parser.add_argument(
        "--namespace", default="default", help="QuickSight 命名空间 (默认: default)"
    )
    parser.add_argument(
        "--region", default="us-east-1", help="AWS 区域 (默认: us-east-1)"
    )
    parser.add_argument("--profile", default=None, help="AWS CLI profile 名称")
    parser.add_argument(
        "--dry-run", action="store_true", help="仅检查，不执行实际操作"
    )
    args = parser.parse_args()

    print()
    print(f"{BOLD}==========================================")
    print(f"  QuickSight 批量开通脚本")
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

    # --- 检查 QuickSight 账号 ---
    log_section("检查 QuickSight 账号")
    qs = session.client("quicksight")
    try:
        desc = qs.describe_account_settings(AwsAccountId=account_id)
        settings = desc.get("AccountSettings", {})
        edition = settings.get("Edition", "UNKNOWN")
        log_ok(f"QuickSight 版本: {edition}")
        log_ok(f"默认命名空间: {settings.get('DefaultNamespace', 'default')}")
    except ClientError as e:
        if "ResourceNotFoundException" in str(e) or "not signed up" in str(e).lower():
            die(
                "此 AWS 账号尚未开通 QuickSight。请先在控制台开通:\n"
                "  https://quicksight.aws.amazon.com/"
            )
        die(f"无法获取 QuickSight 账号信息: {e}")

    # --- 读取邮件列表 ---
    log_section("读取邮件列表")
    emails = read_emails(args.emails_file)
    log_info(f"从 {args.emails_file} 中读取到 {len(emails)} 个邮箱地址")

    # --- 获取现有用户 ---
    log_section("获取现有用户")
    existing_emails = set()
    try:
        paginator = qs.get_paginator("list_users")
        for page in paginator.paginate(
            AwsAccountId=account_id, Namespace=args.namespace
        ):
            for user in page.get("UserList", []):
                existing_emails.add(user.get("Email", "").lower())
        log_ok(f"当前已有 {len(existing_emails)} 个用户")
    except ClientError as e:
        log_warn(f"无法列出现有用户: {e}")

    # --- 配置摘要 ---
    log_section("配置摘要")
    new_count = sum(1 for e in emails if e.lower() not in existing_emails)
    existing_count = len(emails) - new_count
    print(f"  账号:       {account_id}")
    print(f"  区域:       {args.region}")
    print(f"  版本:       {edition}")
    print(f"  角色:       {args.role}")
    print(f"  身份类型:   {args.identity_type}")
    print(f"  命名空间:   {args.namespace}")
    print(f"  总邮箱数:   {len(emails)}")
    print(f"  新增用户:   {new_count}")
    print(f"  已存在:     {existing_count}")
    print(f"  Dry Run:    {args.dry_run}")
    print()

    if not args.dry_run and new_count > 0:
        print(f"{YELLOW}即将注册 {new_count} 个新 QuickSight 用户 (角色: {args.role}){NC}")
        confirm = input("确认执行? (输入 YES 继续): ").strip()
        if confirm != "YES":
            print("已取消")
            return
    elif new_count == 0:
        log_info("所有用户已存在，无需操作")
        return

    # --- 逐个注册 ---
    log_section("注册用户")
    success = 0
    skipped = 0
    failed = 0
    failed_emails = []
    invitation_urls = []

    for email in emails:
        print(f"\n--- 处理: {BOLD}{email}{NC}")

        if email.lower() in existing_emails:
            log_info("用户已存在，跳过")
            skipped += 1
            continue

        if args.dry_run:
            log_info(f"[DRY RUN] 将注册为 {args.role}: {email}")
            skipped += 1
            continue

        ok, msg = register_user(
            qs, account_id, args.namespace, email, args.role, args.identity_type
        )

        if ok:
            log_ok(f"已注册: {email} ({msg})")
            success += 1
            if msg.startswith("http"):
                invitation_urls.append((email, msg))
        else:
            log_error(f"注册失败: {email} — {msg}")
            failed += 1
            failed_emails.append(f"{email} ({msg})")

        time.sleep(0.3)

    # --- 结果 ---
    log_section("执行结果")
    print(f"  总数:     {len(emails)}")
    print(f"  {GREEN}成功:     {success}{NC}")
    if skipped > 0:
        print(f"  {YELLOW}跳过:     {skipped}{NC}")
    if failed > 0:
        print(f"  {RED}失败:     {failed}{NC}")

    if invitation_urls:
        print()
        log_info("注册链接 (QUICKSIGHT 身份类型，用户需通过此链接激活):")
        for email, url in invitation_urls:
            print(f"  {email}: {url}")

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
        print(f"{YELLOW}[DRY RUN] 未执行实际操作。移除 --dry-run 开始正式执行。{NC}")
    elif failed == 0:
        print(f"{GREEN}{BOLD}全部完成!{NC}")
        if args.identity_type == "QUICKSIGHT":
            print()
            log_info("QUICKSIGHT 身份类型的用户需要通过注册链接或邮件激活。")
            log_info(f"QuickSight 控制台: https://{args.region}.quicksight.aws.amazon.com/")
    else:
        print(f"{YELLOW}部分用户注册失败，请检查失败列表后重试。{NC}")
    print()


if __name__ == "__main__":
    main()
