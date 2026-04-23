# Hosted Portal Deployment

## 1. 这份说明解决什么问题

这份文档只用于保留 `hosted portal` 的部署方法，不代表当前项目主线已经转向公网产品。

部署完成后，使用者可以直接打开一个网页：

- 输入任务描述
- 填一个公开 `http/https` Git 仓库地址，或者保留系统自带示例仓库
- 在同一页里查看运行结果

这套流程对应当前的 `serve-portal` 入口：

```bash
python -m repo_harness_lab.cli.main serve-portal --host 127.0.0.1 --port 8765 --public-base-url https://portal.example.com --hosted-mode
```

只要传入 `--public-base-url`，当前实现就会自动切到 hosted mode；这里仍然保留 `--hosted-mode`，是为了让部署命令更明确。

## 2. 当前 hosted mode 的边界

- 线上模式只接受公开 `http/https` Git 仓库地址，或者默认示例仓库。
- 线上模式会拒绝服务器本地路径、`file://`、`ssh://` 和 `git@host:repo.git` 这类地址。
- 私有仓库授权目前还没接入。
- 异步运行任务目前保存在内存里，服务重启后，排队中或运行中的任务会丢失。
- 仓库 clone 和工作区都会落到 `REPO_HARNESS_LAB_RUNTIME_ROOT/tmp`。
- 运行记录和报告会分别落到 `REPO_HARNESS_LAB_RUNTIME_ROOT/runs` 与 `REPO_HARNESS_LAB_RUNTIME_ROOT/reports`。

## 3. 推荐部署形态

如果只是保留一套单机 `hosted portal` 部署能力，推荐先用这一版最小拓扑：

- 一台 Linux 主机
- `systemd` 常驻 `serve-portal`
- `nginx` 做反向代理和 HTTPS
- `git` 负责拉取用户提交的公开仓库
- 模型提供方 API 负责实际运行

推荐目录：

- 应用代码：`/srv/repo-harness-lab/app`
- 运行数据：`/srv/repo-harness-lab/runtime`
- 环境变量：`/etc/repo-harness-lab/portal.env`

## 4. 服务器前置条件

至少准备：

- Linux
- Python `3.11+`
- `git`
- `nginx`
- 一个可访问模型提供方 API 的网络环境
- 一个可访问公开 Git 仓库的网络环境

Debian / Ubuntu 示例：

```bash
sudo apt update
sudo apt install -y git nginx python3.11 python3.11-venv
```

创建专用用户与目录：

```bash
sudo useradd --system --create-home --home-dir /srv/repo-harness-lab repoharness
sudo mkdir -p /srv/repo-harness-lab /etc/repo-harness-lab
sudo chown -R repoharness:repoharness /srv/repo-harness-lab
```

## 5. 安装应用

以 `repoharness` 用户执行：

```bash
sudo -u repoharness git clone <your-repo-url> /srv/repo-harness-lab/app
sudo -u repoharness python3.11 -m venv /srv/repo-harness-lab/app/.venv
sudo -u repoharness /srv/repo-harness-lab/app/.venv/bin/pip install -e /srv/repo-harness-lab/app
sudo -u repoharness mkdir -p /srv/repo-harness-lab/runtime
```

当前项目没有额外运行时依赖，`pip install -e .` 即可。

## 6. 环境变量

复制模板：

```bash
sudo cp /srv/repo-harness-lab/app/examples/deployment/portal.env.example /etc/repo-harness-lab/portal.env
sudo chown root:repoharness /etc/repo-harness-lab/portal.env
sudo chmod 640 /etc/repo-harness-lab/portal.env
```

至少要改这些值：

- `PORTAL_PUBLIC_BASE_URL`
- `PORTAL_PROVIDER`
- `PORTAL_MODEL`
- `PORTAL_API_KEY_ENV`
- 对应提供方的 API key，例如 `DASHSCOPE_API_KEY`

核心环境变量说明：

- `REPO_HARNESS_LAB_PROJECT_ROOT`
  - 项目根目录，通常就是仓库 clone 后的位置
- `REPO_HARNESS_LAB_RUNTIME_ROOT`
  - 运行数据目录，保存 `tmp / runs / reports`
- `REPO_HARNESS_LAB_KEEP_WORKSPACES`
  - `0` 表示跑完自动清理临时工作区
  - `1` 表示保留工作区，便于排查问题
- `PORTAL_PUBLIC_BASE_URL`
  - 对外访问的完整域名，例如 `https://portal.example.com`

## 7. 启动脚本

仓库里已经提供模板脚本：

- `examples/deployment/start_hosted_portal.sh`

这个脚本会：

- 读取环境变量
- 自动带上 `--public-base-url`
- 强制启用 `--hosted-mode`
- 启动 live portal

首次部署先给它执行权限：

```bash
sudo chmod +x /srv/repo-harness-lab/app/examples/deployment/start_hosted_portal.sh
```

手工 smoke test：

```bash
sudo -u repoharness bash -lc 'set -a && source /etc/repo-harness-lab/portal.env && set +a && /srv/repo-harness-lab/app/examples/deployment/start_hosted_portal.sh'
```

如果启动正常，服务会打印一个 `portal_url`，你也可以直接检查：

```bash
curl http://127.0.0.1:8765/api/config
```

返回里应能看到：

- `public_base_url`
- `hosted_mode: true`

## 8. 配置 systemd

复制模板：

```bash
sudo cp /srv/repo-harness-lab/app/examples/deployment/repo-harness-lab-portal.service /etc/systemd/system/repo-harness-lab-portal.service
```

然后按你的实际路径改这几个字段：

- `User`
- `Group`
- `WorkingDirectory`
- `ExecStart`
- `EnvironmentFile`

加载并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now repo-harness-lab-portal
sudo systemctl status repo-harness-lab-portal
```

查看日志：

```bash
sudo journalctl -u repo-harness-lab-portal -f
```

## 9. 配置 nginx

复制模板：

```bash
sudo cp /srv/repo-harness-lab/app/examples/deployment/nginx.repo-harness-lab-portal.conf /etc/nginx/sites-available/repo-harness-lab-portal.conf
sudo ln -s /etc/nginx/sites-available/repo-harness-lab-portal.conf /etc/nginx/sites-enabled/repo-harness-lab-portal.conf
```

把模板里的：

- `portal.example.com`

替换成你的真实域名，然后检查和重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

HTTPS 可以直接配合 `certbot --nginx` 完成。

## 10. 部署后的自检清单

- 域名已指向 nginx 所在机器
- `https://your-domain/harness-portal.html` 能打开
- 页面里默认展示 hosted mode 文案
- 输入公开 Git 仓库地址后可以预览
- 点击运行后，页面能轮询并返回运行结果
- 非法输入服务器本地路径时，网页会被拒绝
- `runtime/tmp`、`runtime/runs`、`runtime/reports` 都可写
- 模型 API key 生效

## 11. 存储与清理

当前运行时目录：

- `runtime/tmp`
  - 仓库 clone、工作区、副本都在这里
- `runtime/runs`
  - 每次运行的记录与证据
- `runtime/reports`
  - HTML 报告与 portal 页面

建议：

- 默认保持 `REPO_HARNESS_LAB_KEEP_WORKSPACES=0`
- 定期清理 `runtime/tmp`
- 如果 `runtime/runs` 和 `runtime/reports` 需要长期保留，再单独做备份

## 12. 当前不在范围内

- 当前 async job store 在内存里，服务重启后不会恢复。
- 当前没有多实例共享任务队列。
- 当前没有私有仓库 token / OAuth 流程。
- 当前没有登录、配额、限流、审计和用户隔离。

## 13. 模板文件

这次一并提供：

- `examples/deployment/portal.env.example`
- `examples/deployment/start_hosted_portal.sh`
- `examples/deployment/repo-harness-lab-portal.service`
- `examples/deployment/nginx.repo-harness-lab-portal.conf`

如果只是部署一套单机 `hosted portal`，这四个文件已经够用。
