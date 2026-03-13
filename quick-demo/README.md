# QuickSight 批量开通脚本

从邮件列表文件中批量读取邮箱地址，通过 QuickSight `register-user` API 注册用户。

## 项目结构

```
quick-demo/
├── batch_register_quicksight.py    # 主脚本 (Python/boto3)
├── batch_register_quicksight.sh    # Shell 入口 (自动检查依赖)
├── emails.txt                      # 邮件列表 (示例)
└── README.md
```

## 前置条件

- **Python 3.10+** 和 **boto3**
- **AWS CLI** 已配置凭证
- **QuickSight** 已在目标账号开通
- **IAM 权限**：`quicksight:RegisterUser`, `quicksight:ListUsers`, `quicksight:DescribeAccountSettings`

## 用法

```bash
# 编辑邮件列表
vi emails.txt

# 先 dry-run 检查
./batch_register_quicksight.sh emails.txt --dry-run

# 注册为 READER (默认)
./batch_register_quicksight.sh emails.txt

# 注册为 AUTHOR
./batch_register_quicksight.sh emails.txt --role AUTHOR

# 注册为 ADMIN_PRO
./batch_register_quicksight.sh emails.txt --role ADMIN_PRO

# 使用 IAM Identity Center 身份
./batch_register_quicksight.sh emails.txt --identity-type IAM_IDENTITY_CENTER

# 指定区域
./batch_register_quicksight.sh emails.txt --region us-west-2
```

## 选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--role` | 用户角色 | READER |
| `--identity-type` | 身份类型 | QUICKSIGHT |
| `--namespace` | 命名空间 | default |
| `--region` | AWS 区域 | us-east-1 |
| `--profile` | AWS CLI profile | 默认 |
| `--dry-run` | 仅检查 | 关闭 |

## 角色说明

| 角色 | 说明 |
|------|------|
| **READER** | 只读 — 查看仪表板 |
| **AUTHOR** | 创作者 — 创建数据源、数据集、分析和仪表板 |
| **ADMIN** | 管理员 — 拥有完全权限 |
| **READER_PRO** | Reader + Q 功能 |
| **AUTHOR_PRO** | Author + Q 功能 |
| **ADMIN_PRO** | Admin + Q 功能 |

## 身份类型

| 类型 | 说明 |
|------|------|
| **QUICKSIGHT** | QuickSight 原生账号（用户通过邀请链接激活） |
| **IAM** | IAM 联合身份 |
| **IAM_IDENTITY_CENTER** | IAM Identity Center 身份 |

## 注意事项

1. **幂等性**：已存在的用户会自动跳过
2. **激活**：QUICKSIGHT 身份类型的用户需通过注册链接激活
3. **失败重试**：失败列表保存到 `<原文件名>_failed.txt`
4. **费用**：每个注册用户会按 QuickSight 定价计费
