# ShadowFleet 远程调试指南

> Debian 12 · VS Code Remote-SSH / PyCharm Professional · Debugpy + pydevd

---

## 目录

1. [方案选择](#1-方案选择)
2. [VS Code Remote-SSH 全断点调试](#2-vs-code-remote-ssh-全断点调试)
3. [PyCharm Professional 远程调试](#3-pycharm-professional-远程调试)
4. [Debugpy 无 IDE 断点调试](#4-debugpy-无-ide-断点调试)
5. [Systemd 服务调试](#5-systemd-服务调试)
6. [Streamlit UI 调试](#6-streamlit-ui-调试)
7. [Daemon 守护进程调试](#7-daemon-守护进程调试)
8. [常见问题排查](#8-常见问题排查)

---

## 1. 方案选择

| 调试场景 | 推荐方案 | 工具 |
|----------|----------|------|
| **开发阶段**（改动频繁） | VS Code Remote-SSH | `debugpy` |
| **生产环境**（临时加断点） | Debugpy 独立端口 | `debugpy` |
| **复杂断点/条件断点** | PyCharm Professional | `pydevd` |
| **Streamlit 页面调试** | VS Code + Chrome DevTools | Streamlit 内置 |
| **多线程/异步调试** | PyCharm Professional | `pydevd` |

---

## 2. VS Code Remote-SSH 全断点调试

### 2.1 服务器端准备

```bash
# 以 shadowfleet 用户登录服务器
ssh shadowfleet@<SERVER_IP>

# 安装依赖
cd ~/ShadowFleet
source venv/bin/activate

# 安装 debugpy（支持异步、多线程、热重载断点）
pip install debugpy

# 确认 Python 路径
which python
# 输出: /home/shadowfleet/ShadowFleet/venv/bin/python
```

### 2.2 本地 VS Code 安装 Remote-SSH 插件

在本地 VS Code 中：

1. 安装插件：`Remote - SSH`（Microsoft 官方）
2. 安装插件：`Python`（Microsoft 官方）
3. 按 `F1` → 输入 `Remote-SSH: Connect to Host...`
4. 选择 `Add New SSH Host`
5. 输入：`ssh shadowfleet@<SERVER_IP>`
6. 选择 SSH 配置文件路径（默认即可）
7. 输入服务器密码（推荐配置 SSH Key 免密登录）

### 2.3 配置 SSH Key 免密登录（推荐）

**本地 Windows PowerShell**：

```powershell
# 生成 SSH 密钥（如果还没有）
ssh-keygen -t ed25519 -C "shadowfleet-dev"

# 上传公钥到服务器
cat $HOME/.ssh/id_ed25519.pub | ssh shadowfleet@<SERVER_IP> "mkdir -p ~/.ssh && cat >> ~/.bashrc"
```

**或手动方式**：

```bash
# 本地生成后上传
# Windows: 将 C:\Users\<用户名>\.ssh\id_ed25519.pub 的内容
# 追加到服务器 ~/.ssh/authorized_keys
```

### 2.4 VS Code 调试配置

在服务器上编辑调试配置：

```bash
# 在 ShadowFleet 项目根目录创建 .vscode 目录
mkdir -p ~/ShadowFleet/.vscode
nano ~/ShadowFleet/.vscode/launch.json
```

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "ShadowFleet: Debug Daemon",
            "type": "debugpy",
            "request": "launch",
            "cwd": "/home/shadowfleet/ShadowFleet",
            "python": "/home/shadowfleet/ShadowFleet/venv/bin/python",
            "program": "/home/shadowfleet/ShadowFleet/daemon.py",
            "args": [],
            "env": {
                "SF_CONFIG_PATH": "/home/shadowfleet/ShadowFleet/config.prod.yaml",
                "AWS_ACCESS_KEY_ID": "AKIAXXXXXXXXXXXXX",
                "AWS_SECRET_ACCESS_KEY": "xxxxxxxxxxxxxxxx",
                "AWS_DEFAULT_REGION": "ap-northeast-1"
            },
            "console": "integratedTerminal",
            "justMyCode": true,
            "redirectOutput": true,
            "django": false,
            "gevent": false
        },
        {
            "name": "ShadowFleet: Debug Streamlit UI",
            "type": "debugpy",
            "request": "launch",
            "cwd": "/home/shadowfleet/ShadowFleet",
            "module": "streamlit",
            "python": "/home/shadowfleet/ShadowFleet/venv/bin/python",
            "args": [
                "run",
                "app.py",
                "--server.port",
                "8501",
                "--server.address",
                "127.0.0.1"
            ],
            "env": {
                "SF_CONFIG_PATH": "/home/shadowfleet/ShadowFleet/config.prod.yaml",
                "AWS_ACCESS_KEY_ID": "AKIAXXXXXXXXXXXXX",
                "AWS_SECRET_ACCESS_KEY": "xxxxxxxxxxxxxxxx",
                "AWS_DEFAULT_REGION": "ap-northeast-1"
            },
            "console": "integratedTerminal",
            "justMyCode": true
        },
        {
            "name": "ShadowFleet: Attach to Daemon (Remote)",
            "type": "debugpy",
            "request": "attach",
            "host": "localhost",
            "port": 5678,
            "waitForClient": true,
            "cwd": "/home/shadowfleet/ShadowFleet",
            "justMyCode": true
        },
        {
            "name": "ShadowFleet: Pytest (Current File)",
            "type": "debugpy",
            "request": "launch",
            "cwd": "${workspaceFolder}",
            "module": "pytest",
            "args": [
                "${file}",
                "-v",
                "-s",
                "--tb=short"
            ],
            "python": "/home/shadowfleet/ShadowFleet/venv/bin/python",
            "justMyCode": false
        },
        {
            "name": "ShadowFleet: Unit Tests",
            "type": "debugpy",
            "request": "launch",
            "cwd": "/home/shadowfleet/ShadowFleet",
            "module": "pytest",
            "args": [
                "tests/unit",
                "-v",
                "-s",
                "--tb=short",
                "--cov=.",
                "--cov-report=term-missing"
            ],
            "python": "/home/shadowfleet/ShadowFleet/venv/bin/python",
            "console": "integratedTerminal",
            "justMyCode": false
        }
    ]
}
```

### 2.5 VS Code settings.json 配置

```bash
nano ~/ShadowFleet/.vscode/settings.json
```

```json
{
    "python.defaultInterpreterPath": "/home/shadowfleet/ShadowFleet/venv/bin/python",
    "python.analysis.typeCheckingMode": "basic",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": false,
    "python.linting.flake8Enabled": true,
    "python.formatting.provider": "black",
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": [
        "tests/unit",
        "-v"
    ],
    "files.associations": {
        "*.py": "python"
    },
    "editor.formatOnSave": true,
    "editor.rulers": [88, 120],
    "[python]": {
        "editor.defaultFormatter": "ms-python.black-formatter",
        "editor.formatOnSave": true,
        "editor.codeActionsOnSave": {
            "source.organizeImports": "explicit"
        }
    }
}
```

### 2.6 断点调试完整流程

**步骤 1**：在 VS Code 中打开远程项目

```
F1 → Remote-SSH: Connect to Host → shadowfleet@<SERVER_IP>
→ 打开文件夹 /home/shadowfleet/ShadowFleet
```

**步骤 2**：选择 Python 解释器

```
F1 → Python: Select Interpreter
→ 选择 /home/shadowfleet/ShadowFleet/venv/bin/python
```

**步骤 3**：打开 `daemon.py`，在关键位置打上断点

```python
# daemon.py 第 15 行附近
def main():
    # 在此处 F9 打上断点
    daemon_service.start()  # ← 断点打在这里
```

**步骤 4**：按 `F5` 启动调试

- 左侧 `RUN AND DEBUG` 面板选择 `ShadowFleet: Debug Daemon`
- 按 `F5`，VS Code 会在断点处停下
- 可以查看变量、单步执行、查看调用栈

---

## 3. PyCharm Professional 远程调试

> PyCharm Professional 内置 SSH Remote Debugger，比 VS Code 配置更简单

### 3.1 配置 Deployment（代码同步）

`File → Settings → Build, Execution, Deployment → Deployment`

点击 `+` → `SFTP`：

| 配置项 | 值 |
|--------|-----|
| `SFTP host` | `<SERVER_IP>` |
| `Port` | `22` |
| `User name` | `shadowfleet` |
| `Auth type` | `Key pair` |
| `Private key file` | 本地 `C:\Users\<用户名>\.ssh\id_ed25519` |
| `Root path` | `/home/shadowfleet/ShadowFleet` |
| `Web server URL` | `https://shadow.rensw.xyz` |

切换到 `Mappings` 标签：

| 配置项 | 值 |
|--------|-----|
| `Local path` | `d:\tanxuan\project\ShadowFleet` |
| `Deployment path` | `/home/shadowfleet/ShadowFleet` |
| `Web path` | `/` |

**同步代码**：`Tools → Deployment → Sync to Remote Host`

### 3.2 配置 Python Remote Interpreter

`File → Settings → Project: ShadowFleet → Python Interpreter`

点击 `⚙ → Add... → SSH Interpreter → Existing server configuration`

选择已保存的 SSH 配置，或新建：

| 配置项 | 值 |
|--------|-----|
| `Host` | `<SERVER_IP>` |
| `Port` | `22` |
| `User name` | `shadowfleet` |
| `Auth type` | `Key pair` |
| `Private key` | `C:\Users\<用户名>\.ssh\id_ed25519` |

下一步：

| 配置项 | 值 |
|--------|-----|
| `Python interpreter path` | `/home/shadowfleet/ShadowFleet/venv/bin/python` |
| `Sync folders` | 本地项目 ↔ `/home/shadowfleet/ShadowFleet` |
| `Automatically sync` | ✅ |

### 3.3 配置 Run/Debug Configurations

`Run → Edit Configurations → + → Python Remote Debug`

| 配置项 | 值 |
|--------|-----|
| `Name` | `ShadowFleet Daemon Debug` |
| `Host` | `localhost` |
| `Port` | `10123` |
| `Path mappings` | `d:\tanxuan\project\ShadowFleet` → `/home/shadowfleet/ShadowFleet` |
| `Attach to subprocess` | ✅ |

### 3.4 PyCharm 调试完整流程

**步骤 1**：在服务器上手动启动带调试端口的进程

```bash
ssh shadowfleet@<SERVER_IP>
cd ~/ShadowFleet
source venv/bin/activate

# 安装 pydevd（PyCharm 内置 pydevd_pycharm 插件需要）
pip install pydevd_pycharm

# 启动 Daemon，开启 PyCharm 远程调试端口
python -m pydevd_pycharm --multiprocess --port 10123 --host 0.0.0.0 daemon.py
```

**步骤 2**：在 PyCharm 中按 `Shift+F9` 启动调试

- 在 `daemon.py` 中打上断点
- PyCharm 会自动 attach 到服务器上的进程
- 触发断点条件后停下

**步骤 3**：Streamlit UI 调试

在 PyCharm 中新建 `Python` 运行配置：

```python
# 模块方式运行
Module name: streamlit
Parameters: run app.py --server.port 8501 --server.address 127.0.0.1
Python interpreter: shadowfleet@<SERVER_IP> (remote)
```

**步骤 4**：Attach 到已运行的进程

如果 Daemon 已经通过 systemd 在后台运行：

```bash
# 查找进程 PID
ps aux | grep daemon.py | grep -v grep
# 输出: shadowfle+  12345  ... /home/shadowfleet/ShadowFleet/venv/bin/python daemon.py

# 在另一个终端（服务器上），使用 pydevd 连接
cd ~/ShadowFleet
source venv/bin/activate
python -m pydevd_pycharm --attach --port 10123 --pid 12345
```

PyCharm 端：`Run → Attach to Process` → 选择对应进程。

---

## 4. Debugpy 无 IDE 断点调试

适用于临时在生产环境加断点，不需要 IDE 直接连接。

### 4.1 服务器端：启动 Debug Server

```bash
# 在 ShadowFleet 目录
cd ~/ShadowFleet
source venv/bin/activate

# 安装 debugpy
pip install debugpy

# 启动 Daemon，监听 5678 端口（阻塞模式，生产慎用）
python -m debugpy --listen 0.0.0.0:5678 --wait-for-client daemon.py
```

### 4.2 本地：VS Code Attach 到远程

VS Code `launch.json` 中已配置 `Attach to Daemon (Remote)`：

```json
{
    "name": "ShadowFleet: Attach to Daemon (Remote)",
    "type": "debugpy",
    "request": "attach",
    "host": "<SERVER_IP>",
    "port": 5678,
    "waitForClient": true
}
```

按 `F5`，VS Code 会等待 `wait-for-client` 连接后自动断点。

### 4.3 安全的 Debugpy 使用方式（生产环境）

```bash
# 只在需要调试时临时开启，调试完立即关闭
# 方法：修改 systemd 服务，加一个 Debug 模式启动脚本

sudo nano /usr/local/bin/shadowfleet-debug.sh
```

```bash
#!/bin/bash
# /usr/local/bin/shadowfleet-debug.sh
# 临时调试启动脚本（仅调试时使用）

DEBUG_PORT=5678
DEBUG_HOST="0.0.0.0"

cd /home/shadowfleet/ShadowFleet
source venv/bin/activate

echo "[DEBUG] Starting ShadowFleet Daemon with debug port ${DEBUG_PORT}..."
python -m debugpy \
    --listen "${DEBUG_HOST}:${DEBUG_PORT}" \
    --wait-for-client \
    daemon.py
```

```bash
sudo chmod +x /usr/local/bin/shadowfleet-debug.sh

# 停止当前服务
sudo systemctl stop shadowfleet-daemon

# 手动启动调试模式
sudo -u shadowfleet /usr/local/bin/shadowfleet-debug.sh

# 调试完成后恢复
sudo systemctl start shadowfleet-daemon
```

### 4.4 VS Code attach 配置（远程非监听模式）

如果服务器启动了 debug server，本地 VS Code 只需 attach：

```json
{
    "name": "Attach to Remote (via SSH tunnel)",
    "type": "debugpy",
    "request": "attach",
    "host": "localhost",
    "port": 5678,
    "subprocess": true,
    "justMyCode": false
}
```

**建立 SSH 隧道**（本地 Windows PowerShell）：

```powershell
ssh -L 5678:localhost:5678 shadowfleet@<SERVER_IP> -N
```

---

## 5. Systemd 服务调试

### 5.1 查看 systemd 服务的详细日志

```bash
# 实时跟踪日志（带时间戳）
sudo journalctl -u shadowfleet-daemon -f --all -o short-iso

# 只看 ERROR 及以上
sudo journalctl -u shadowfleet-daemon -p err -f

# 从指定时间开始
sudo journalctl -u shadowfleet-daemon --since "10 minutes ago"

# 查看完整日志（含启动前的日志）
sudo journalctl -u shadowfleet-daemon -e --no-pager

# 导出日志到文件
sudo journalctl -u shadowfleet-daemon --since "2026-03-25 00:00:00" > ~/shadowfleet-daemon.log
```

### 5.2 修改 systemd 服务开启调试

```bash
# 创建调试版服务文件
sudo nano /etc/systemd/system/shadowfleet-daemon-debug.service
```

```ini
[Unit]
Description=ShadowFleet Daemon - DEBUG MODE
After=network.target

[Service]
Type=simple
User=shadowfleet
Group=shadowfleet
WorkingDirectory=/home/shadowfleet/ShadowFleet
EnvironmentFile=/home/shadowfleet/.shadowfleet_env

# 启用标准输入、debugpy 调试端口
ExecStart=/home/shadowfleet/ShadowFleet/venv/bin/python -m debugpy \
    --listen 0.0.0.0:5678 \
    --wait-for-client \
    /home/shadowfleet/ShadowFleet/daemon.py

# 调试模式：失败不重启，方便查看崩溃现场
Restart=no

StandardOutput=journal
StandardError=journal
SyslogIdentifier=shadowfleet-daemon-debug

[Install]
WantedBy=multi-user.target
```

```bash
# 重新加载并启动调试服务
sudo systemctl daemon-reload
sudo systemctl stop shadowfleet-daemon
sudo systemctl enable shadowfleet-daemon-debug
sudo systemctl start shadowfleet-daemon-debug

# 查看状态
sudo systemctl status shadowfleet-daemon-debug --no-pager -l

# 完成后恢复原服务
sudo systemctl stop shadowfleet-daemon-debug
sudo systemctl start shadowfleet-daemon
```

### 5.3 检查服务启动失败原因

```bash
# 查看启动失败原因
sudo systemctl status shadowfleet-daemon

# 查看内核日志中的相关信息
sudo dmesg | grep shadowfleet

# 检查环境变量是否正确加载
sudo systemctl show shadowfleet-daemon | grep Environment

# 手动模拟启动（排查配置问题）
sudo su - shadowfleet -c "source ~/.shadowfleet_env && /home/shadowfleet/ShadowFleet/venv/bin/python /home/shadowfleet/ShadowFleet/daemon.py"
```

---

## 6. Streamlit UI 调试

### 6.1 VS Code 调试 Streamlit（推荐）

使用前面 `launch.json` 中的 `ShadowFleet: Debug Streamlit UI` 配置：

```json
{
    "name": "ShadowFleet: Debug Streamlit UI",
    "type": "debugpy",
    "request": "launch",
    "module": "streamlit",
    "args": [
        "run",
        "app.py",
        "--server.port",
        "8501",
        "--server.address",
        "127.0.0.1"
    ],
    "env": {
        "SF_CONFIG_PATH": "/home/shadowfleet/ShadowFleet/config.prod.yaml"
    }
}
```

按 `F5` 即可在断点处停下。Streamlit 支持 **热重载**，修改代码后自动刷新页面。

### 6.2 Streamlit 页面级调试（Chrome DevTools）

Streamlit 页面本质上是一个 Web 应用，可以通过浏览器开发者工具调试：

1. 在浏览器中打开 `https://shadow.rensw.xyz`
2. 按 `F12` 打开 Chrome DevTools
3. 切换到 `Sources` 面板，查找 `localhost:8501` 的映射文件
4. 在 Python 源文件对应位置打断点（通过 Source Map）

**注意**：Streamlit 的 Source Map 映射可能不完整，复杂断点建议用上面的 VS Code/PyCharm 方案。

### 6.3 Streamlit 性能分析

```python
# 在 services/ 代码中临时添加 profiling
import time
import functools

def profile(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"[PROFILE] {func.__name__} took {elapsed:.4f}s")
        return result
    return wrapper

# 使用方式：在关键函数加装饰器
@profile
def expensive_dashboard_query():
    ...
```

### 6.4 Streamlit 热重载

```bash
# 在服务器上手动启动 Streamlit（开发模式，热重载开启）
cd ~/ShadowFleet
source venv/bin/activate
streamlit run app.py \
    --server.port 8501 \
    --server.address 127.0.0.1 \
    --server.runOnSave true \
    --server.headless false
```

---

## 7. Daemon 守护进程调试

### 7.1 多线程调试

ShadowFleet Daemon 使用多线程架构：

| 线程名 | 职责 | 调试难度 |
|--------|------|----------|
| `MainThread` | 启动、初始化、主循环 | ⭐ |
| `provisioning_worker` | 节点初始化任务 | ⭐⭐⭐ |
| `sentinel_worker` | 健康检查、自愈触发 | ⭐⭐⭐ |
| `manual_operation_worker` | 手动操作队列 | ⭐⭐ |
| `ready_callback_http` | HTTP 服务、回调处理 | ⭐⭐ |

**VS Code 多线程调试**：

1. 在 `RUN AND DEBUG` 面板点击 `⋮ → Thread` 可以查看所有线程
2. 在 `Call Stack` 面板可以切换到不同线程的调用栈
3. 条件断点：右键断点 → `Edit Breakpoint...` → 输入条件（如 `node_id == "i-abc123"`）

```python
# 条件断点示例（在 services/healer_service.py 中）
# 假设有 node_id 变量，打上条件断点：
# node_id == "i-0x1234567890abcdef"
```

### 7.2 日志断点（Logpoints）

VS Code 支持不暂停代码执行的日志断点（类似 `print` 但不破坏流程）：

右键断点 → `Edit Breakpoint...` → 选择 `Log Message`：

```
# 日志断点示例
[DEBUG] node_id={node_id}, status={status}, correlation_id={correlation_id}
```

### 7.3 异步调试（async/await）

ShadowFleet 的 Sentinel 和 Probe 模块大量使用 `asyncio`：

```python
# 在 async 函数中打断点，VS Code 自动识别
async def sentinel_probe_cycle():
    results = await probe_orchestrator.execute(
        node_id=node_id,
        mode="cn_probe_mesh"
    )
    # ↑ 在此处打断点，VS Code 支持异步调用栈
```

### 7.4 完整调试流程示例

假设要调试 `healer_service.py` 中的节点自愈逻辑：

```bash
# 1. 服务器端启动带调试端口的 Daemon
cd ~/ShadowFleet
source venv/bin/activate
python -m debugpy --listen 0.0.0.0:5678 --wait-for-client daemon.py

# 2. 本地 VS Code（已在 Remote-SSH 模式）
# 打开 healer_service.py，找到 heal_node 函数
# 在第 45 行打断点:
#   result = await self._execute_healing(node_id, correlation_id)

# 3. 按 F5，VS Code attach 到远程
# 触发条件：让某个节点进入异常状态
# → 断点触发，查看变量、调用栈

# 4. 如果是多线程问题
# 在 BREAKPOINTS 面板勾选 "All Exceptions"
# 或在 EXCEPTION BREAKPOINTS 面板勾选 "Raised" 和 "Uncaught"
```

### 7.5 核心调试命令速查

```bash
# --- 服务器端 ---
# 启动调试模式
python -m debugpy --listen 0.0.0.0:5678 daemon.py

# 查看所有 Python 进程
ps aux | grep python

# 查看线程数
ps -eLf | grep daemon | grep -v grep | wc -l

# 实时查看内存/CPU
top -Hp $(pgrep -f daemon.py)

# --- 本地端 ---
# SSH 隧道
ssh -L 5678:localhost:5678 shadowfleet@<SERVER_IP> -N

# 测试端口连通性
telnet <SERVER_IP> 5678
# 或
nc -zv <SERVER_IP> 5678

# 查看 VS Code Remote-SSH 日志
# 本地: %APPDATA%\Code\User\logs 下
```

---

## 8. 常见问题排查

### Q1: VS Code Remote-SSH 连接失败

```
错误: "Could not connect to server"
```

**排查步骤**：

```powershell
# 1. 检查 SSH 服务是否运行
ssh shadowfleet@<SERVER_IP> "echo ok"

# 2. 检查端口
ssh -v shadowfleet@<SERVER_IP> "echo ok"

# 3. 检查服务器 SSH 配置
ssh shadowfleet@<SERVER_IP> "cat /etc/ssh/sshd_config | grep -E '(Port|PermitRoot|Pubkey|Password)'"

# 4. 确认服务器 SSH 服务端口（默认 22）
# 如果是其他端口，在 VS Code 的 SSH 配置中指定
```

**VS Code SSH 配置**（`~/.ssh/config`）：

```
Host shadowfleet-prod
    HostName <SERVER_IP>
    Port 22
    User shadowfleet
    IdentityFile C:\Users\<用户名>\.ssh\id_ed25519
    ForwardAgent yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

### Q2: 断点一直显示"Unverified"

```
断点图标: 空心灰圈，没有变成红色实心
```

**原因**：`justMyCode` 设置为 `true`，但断点打在了第三方库。

**解决**：将断点打在 ShadowFleet 项目代码上（`services/`, `database/`, `ui/` 等目录）。

或者在 `launch.json` 中设置：

```json
"justMyCode": false
```

### Q3: PyCharm Attach 失败 "Could not open debugger port"

```
Error: Could not open debugger port (#10123)
```

**排查步骤**：

```bash
# 1. 确认端口未被占用
sudo ss -tlnp | grep 10123

# 2. 确认防火墙允许
sudo ufw status

# 3. 确认 pydevd 已安装
pip show pydevd-pycharm

# 4. 如果端口被占用，杀掉占用进程
sudo fuser -k 10123/tcp
```

### Q4: Streamlit 在 systemd 下断点无效

```
问题：Streamlit 通过 systemd 启动后，debugpy 无法 attach
```

**原因**：systemd 服务的 `PrivateTmp=true` 可能影响调试。

**解决**：使用前面的 `shadowfleet-daemon-debug.service`，不要直接调试 systemd 主服务。

### Q5: 多线程断点只停一次

```
问题：断点打在线程函数上，但只触发一次
```

**原因**：线程函数可能只执行一次，之后用队列/事件循环。

**解决**：

1. 查看线程是否持续运行：`ps -eLf | grep daemon`
2. 如果是轮询模式，找到轮询循环，在循环内打断点
3. 使用条件断点减少触发次数：`iteration_count > 5`

### Q6: Debugpy 连接后进程卡死

```
问题：attach 成功后，程序一直在等待 client
```

**原因**：`--wait-for-client` 参数导致进程阻塞等待调试器连接。

**解决**：去掉 `--wait-for-client`，改用非阻塞模式：

```bash
# 服务器端（不阻塞）
python -m debugpy --listen 0.0.0.0:5678 daemon.py

# VS Code launch.json
"request": "attach"  # 不加 waitForClient
```

### Q7: 生产环境误开调试端口

```
风险：debugpy 监听 0.0.0.0:5678 相当于对外网开放代码执行权限！
```

**安全准则**：

1. ✅ 调试时只在 LAN/内网环境暴露端口
2. ✅ 调试完成后立即关闭 debugpy
3. ✅ 使用 SSH 隧道访问，不要直接暴露公网端口
4. ✅ 生产环境使用 `--allowed-hosts localhost` 限制
5. ✅ 调试前在 `config.yaml` 中确认 `logging.level: DEBUG`

---

## 调试配置快速参考卡

```
┌─────────────────────────────────────────────────────────────┐
│                    调试方式速查表                              │
├──────────────┬──────────────────────────────────────────────┤
│ 场景         │ 命令 / 步骤                                   │
├──────────────┼──────────────────────────────────────────────┤
│ VS Code 调试 │ 1. Remote-SSH 连接                           │
│ Daemon       │ 2. 选择 venv Python                          │
│              │ 3. launch.json → F5                           │
├──────────────┼──────────────────────────────────────────────┤
│ VS Code 调试 │ launch.json → "ShadowFleet: Debug Streamlit" │
│ Streamlit    │ → F5，断点生效                               │
├──────────────┼──────────────────────────────────────────────┤
│ 生产临时     │ 1. 服务器: debugpy --listen 5678 daemon.py   │
│ 断点（危险）  │ 2. 本地 SSH 隧道: ssh -L 5678:localhost:5678 │
│              │ 3. VS Code attach → F5                       │
│              │ ⚠ 调试完立即关闭！                            │
├──────────────┼──────────────────────────────────────────────┤
│ PyCharm 调试 │ 1. Run → Edit Configs → Python Remote Debug   │
│              │ 2. 服务器: pydevd_pycharm --port 10123       │
│              │ 3. PyCharm Shift+F9 attach                   │
├──────────────┼──────────────────────────────────────────────┤
│ Systemd 服务 │ 1. 创建 shadowfleet-daemon-debug.service     │
│ 调试         │ 2. systemctl start shadowfleet-daemon-debug │
│              │ 3. VS Code attach port 5678                  │
├──────────────┼──────────────────────────────────────────────┤
│ 查看日志     │ journalctl -u shadowfleet-daemon -f           │
│              │ journalctl -u shadowfleet-daemon -p err      │
└──────────────┴──────────────────────────────────────────────┘
```
