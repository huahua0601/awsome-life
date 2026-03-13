# Kiro 批量开通脚本

从邮件列表文件中批量读取邮箱地址，自动创建 Kiro Profile（如不存在），在 IAM Identity Center 中查找/创建用户，然后通过 SSO 应用分配为每个用户开通 Kiro 订阅。

## 架构

```
                         ┌─────────────────────────────────┐
  emails.txt ──▶ 脚本 ──▶│  AWS                             │
                         │  ┌───────────────────────────┐   │
                         │  │ 1. 检查/创建 Kiro Profile  │   │
                         │  │    (Q Business API)        │   │
                         │  └────────────┬──────────────┘   │
                         │               ▼                   │
                         │  ┌───────────────────────────┐   │
                         │  │ 2. 查找/创建用户           │   │
                         │  │    (Identity Store API)    │   │
                         │  └────────────┬──────────────┘   │
                         │               ▼                   │
                         │  ┌───────────────────────────┐   │
                         │  │ 3. 分配用户到 Kiro 应用    │   │
                         │  │    (SSO Admin API)         │   │
                         │  └───────────────────────────┘   │
                         └─────────────────────────────────┘
                                        │
                                 用户收到开通邮件
                               (24小时内自动发送)
```

## 项目结构

```
kiro-demo/
├── batch_enable_kiro.py    # 主脚本 (Python/boto3)
├── batch_enable_kiro.sh    # Shell 入口 (自动检查依赖)
├── emails.txt              # 邮件列表 (示例)
└── README.md
```

## 前置条件

- **Python 3.10+** 和 **boto3**
- **AWS CLI** 已配置凭证（`aws configure`）
- **IAM Identity Center** 已在目标区域启用
- **AWS Organizations**（推荐，standalone 账号功能受限）
- **IAM 权限** — 执行者需要以下权限：
  - `sso-admin:ListInstances` / `sso-admin:ListApplications` / `sso-admin:CreateApplicationAssignment`
  - `identitystore:ListUsers` / `identitystore:CreateUser`
  - `qbusiness:CreateApplication`（自动创建 Kiro Profile 时需要）

## 用法

### 1. 准备邮件列表

创建 `emails.txt`，每行一个邮箱：

```
alice@example.com
bob@example.com
charlie@example.com
# 注释行会被忽略
```

### 2. 运行脚本

```bash
# 基本用法 — 默认 Pro 等级
./batch_enable_kiro.sh emails.txt

# 或直接用 Python
python3 batch_enable_kiro.py emails.txt

# 指定订阅等级
./batch_enable_kiro.sh emails.txt --tier Pro+
./batch_enable_kiro.sh emails.txt --tier Power

# 指定区域
./batch_enable_kiro.sh emails.txt --region eu-central-1

# 使用指定 AWS Profile
./batch_enable_kiro.sh emails.txt --profile my-admin-profile

# 先用 dry-run 模式检查
./batch_enable_kiro.sh emails.txt --dry-run

# 自动创建不存在的用户
./batch_enable_kiro.sh emails.txt --create-users

# 组合使用
./batch_enable_kiro.sh emails.txt --tier Pro+ --region us-east-1 --create-users
```

### 选项说明

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--tier <Pro\|Pro+\|Power>` | Kiro 订阅等级 | Pro |
| `--region <region>` | AWS 区域 | us-east-1 |
| `--profile <name>` | AWS CLI profile | 默认 profile |
| `--dry-run` | 仅检查不执行 | 关闭 |
| `--create-users` | 自动创建不存在的用户 | 关闭 |

### 订阅等级

| 等级 | 说明 |
|------|------|
| **Pro** | 基础版 — 适合个人开发者 |
| **Pro+** | 增强版 — 更多配额和功能 |
| **Power** | 高级版 — 无限制使用 |

## 输出示例

```
==========================================
  Kiro 批量开通脚本
==========================================

=== 验证 AWS 凭证 ===
[OK]    AWS Account: 715371302281

=== 读取邮件列表 ===
[INFO]  从 emails.txt 中读取到 3 个邮箱地址

=== 获取 IAM Identity Center 信息 ===
[OK]    Instance ARN:     arn:aws:sso:::instance/ssoins-xxxxx
[OK]    Identity Store:   d-xxxxxxxxxx

=== 检查 Kiro Profile ===
[OK]    Q Developer 应用已创建: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
[OK]    找到 Kiro 应用: arn:aws:sso::XXXX:application/ssoins-XXXX/apl-XXXX

=== 配置摘要 ===
  账号:       715371302281
  区域:       us-east-1
  订阅等级:   Pro
  用户数量:   3

=== 处理用户 ===
--- 处理: alice@example.com
[OK]    找到用户: a1b2c3d4-...
[OK]    Kiro Pro 已开通: alice@example.com

=== 执行结果 ===
  总数:     3
  成功:     3

全部完成! 用户将在 24 小时内收到 Kiro 开通邮件。
```

## 注意事项

1. **支持区域**：Kiro 目前仅支持 `us-east-1` 和 `eu-central-1`
2. **邮件通知**：用户开通后 24 小时内会收到包含下载链接的邮件
3. **幂等性**：重复执行不会产生副作用，已开通的用户会跳过（ConflictException 自动处理）
4. **失败重试**：失败列表会保存到 `<原文件名>_failed.txt`，可直接用于重试
5. **Kiro Profile 自动创建**：脚本会检查是否存在 Kiro Profile，如不存在则通过 Q Business API 自动创建
