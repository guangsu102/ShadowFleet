# ShadowFleet 开发调试指南

## 目录

- [环境准备](#环境准备)
- [启动模式](#启动模式)
- [IDE 调试配置](#ide-调试配置)
- [调试技巧](#调试技巧)
- [常见问题](#常见问题)

---

## 环境准备

### 1. 安装依赖

```bash
# 克隆项目后
cd ShadowFleet

# 创建虚拟环境（推荐）
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置文件

复制并修改 `config.yaml`：

```bash
cp config.yaml config.dev.yaml
```

编辑 `config.dev.yaml` 调整开发环境配置：

```yaml
app:
  environment: development
  # 开发环境关闭哨兵自动监控
  sentinel_enabled: false
  # 缩短轮询间隔加快调试
  daemon_idle_poll_interval_seconds: 1.0
  logging:
    level: DEBUG  # 开启详细日志

telegram:
  enabled: false  # 开发环境关闭通知
```

### 3. 环境变量方式覆盖配置

```bash
# 方式1: 创建 .env 文件
echo "SF_CONFIG_PATH=config.dev.yaml" > .env

# 方式2: 直接设置环境变量
$env:SF_CONFIG_PATH="config.dev.yaml"
```

---

## 启动模式

ShadowFleet 有两个独立的入口：

### 模式 1: Streamlit UI 控制台

```bash
# 开发模式（带热重载）
streamlit run app.py --server.port 8501 --server.runOnSave true

# 生产模式
streamlit run app.py --server.port 8501 --server.headless true

# 指定配置文件
SF_CONFIG_PATH=config.dev.yaml streamlit run app.py
```

**访问地址**: http://localhost:8501

### 模式 2: Daemon 后台服务

```bash
# 开发模式
python daemon.py

# 查看日志输出
python daemon.py 2>&1 | tee daemon.log
```

**Daemon 服务端口**: http://localhost:8787

### 模式 3: 同时运行（推荐开发）

```bash
# 终端1: 启动 Daemon
python daemon.py

# 终端2: 启动 UI
streamlit run app.py
```

---

## IDE 调试配置

### VS Code / Cursor 调试配置

创建 `.vscode/launch.json`：

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Debug Daemon",
      "type": "debugpy",
      "request": "launch",
      "module": "daemon",
      "cwd": "${workspaceFolder}",
      "env": {
        "SF_CONFIG_PATH": "config.dev.yaml"
      },
      "console": "integratedTerminal",
      "justMyCode": false
    },
    {
      "name": "Debug Streamlit UI",
      "type": "debugpy",
      "request": "launch",
      "module": "streamlit",
      "args": ["run", "app.py", "--server.port", "8501"],
      "cwd": "${workspaceFolder}",
      "env": {
        "SF_CONFIG_PATH": "config.dev.yaml"
      },
      "console": "integratedTerminal",
      "justMyCode": false
    },
    {
      "name": "Debug Unit Tests",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["tests/", "-v", "-s"],
      "cwd": "${workspaceFolder}",
      "console": "integratedTerminal",
      "justMyCode": false
    },
    {
      "name": "Debug Single Test",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["tests/${relativeFileDirname}/test_${selectedText}.py", "-v", "-s", "-k", "${selectedText}"],
      "cwd": "${workspaceFolder}",
      "console": "integratedTerminal",
      "justMyCode": false
    }
  ]
}
```

创建 `.vscode/settings.json`：

```json
{
  "python.analysis.typeCheckingMode": "basic",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": false,
  "python.linting.flake8Enabled": true,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": "explicit"
  }
}
```

### PyCharm 调试配置

#### Daemon 调试

1. **Run > Edit Configurations > + > Python**
2. 配置：
   - Name: `Debug Daemon`
   - Script path: `daemon.py`
   - Working directory: 项目根目录
   - Environment variables: `SF_CONFIG_PATH=config.dev.yaml`
   - Python interpreter: 选择虚拟环境

#### Streamlit UI 调试

1. **Run > Edit Configurations > + > Python**
2. 配置：
   - Name: `Debug Streamlit`
   - Module name: `streamlit`
   - Parameters: `run app.py --server.port 8501`
   - Working directory: 项目根目录
   - Environment variables: `SF_CONFIG_PATH=config.dev.yaml`

### 断点调试技巧

#### 在关键位置设置断点

**Daemon 入口** (`daemon.py`):
```python
def main() -> None:
    runtime_context = build_runtime_context()  # ← 断点
    ...
```

**任务处理循环** (`daemon.py`):
```python
def _run_provisioning_worker(...):
    while not stop_event.is_set():
        processed_task = task_service.process_next_task(...)  # ← 断点
        ...
```

**探针回调** (`daemon.py`):
```python
def _handle_ready_callback(self) -> None:
    # ← 断点：所有节点就绪回调都会停在这里
```

---

## 调试技巧

### 1. 日志级别调整

修改 `config.yaml` 或 `config.dev.yaml`：

```yaml
logging:
  level: DEBUG  # TRACE > DEBUG > INFO > WARNING > ERROR
  format: "%(asctime)s | %(levelname)s | %(name)s | correlation_id=%(correlation_id)s | event_type=%(event_type)s | %(message)s"
```

### 2. 启用 Correlation ID 追踪

所有日志都包含 `correlation_id`，便于追踪单次请求：

```
2024-01-15 10:30:45 | INFO | services.provisioner | correlation_id=a1b2c3d4... | event_type=provision_task_processing | Processing provisioning task id=5
```

### 3. 使用 Python REPL 调试

```python
from services.runtime_service import build_runtime_context
from services.provisioning_task_service import ProvisioningTaskService

# 初始化
ctx = build_runtime_context()
task_service = ProvisioningTaskService(ctx)

# 调试：查看任务列表
tasks = task_service.list_recent_tasks(limit=10)
for t in tasks:
    print(f"Task {t.id}: {t.status}")
```

### 4. SQLite 数据库调试

```python
import sqlite3

# 连接数据库
conn = sqlite3.connect('shadowfleet.db')
cursor = conn.cursor()

# 查看所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print(cursor.fetchall())

# 查看任务表
cursor.execute("SELECT * FROM fleet_provisioning_tasks LIMIT 5;")
for row in cursor.fetchall():
    print(row)

conn.close()
```

### 5. 查看实时日志

```bash
# 方法1: 使用 tail
Get-Content -Wait -Path daemon.log

# 方法2: 使用 grep 过滤
Get-Content -Wait daemon.log | Select-String "ERROR"

# 方法3: 颜色高亮
Get-Content daemon.log | ForEach-Object {
    if ($_ -match "ERROR") { Write-Host $_ -ForegroundColor Red }
    elseif ($_ -match "WARN") { Write-Host $_ -ForegroundColor Yellow }
    else { Write-Host $_ }
}
```

---

## 常见问题

### Q1: Streamlit 页面不刷新

```bash
# 清除缓存
streamlit cache clear

# 或重启
streamlit run app.py --server.runOnSave true
```

### Q2: 数据库锁定

```bash
# 删除锁文件
Remove-Item shadowfleet.db-journal -ErrorAction SilentlyContinue
```

### Q3: 端口被占用

```bash
# 查看端口占用
netstat -ano | findstr 8501
netstat -ano | findstr 8787

# 结束进程
taskkill /PID <进程ID> /F
```

### Q4: 依赖安装失败

```bash
# 升级 pip
python -m pip install --upgrade pip

# 单独安装失败的包
pip install psycopg2-binary --no-cache-dir
```

### Q5: 配置不生效

检查配置加载顺序：
1. 环境变量 `SF_CONFIG_PATH`
2. 当前目录 `config.yaml`
3. 默认值

---

## 项目架构速查

```
ShadowFleet/
├── app.py              # Streamlit UI 入口
├── daemon.py           # Daemon 服务入口
├── config.yaml         # 主配置文件
├── shadowfleet.db     # SQLite 本地数据库
│
├── ui/                 # UI 层（只读）
│   ├── pages/         # 页面组件
│   └── runtime.py     # UI 运行时
│
├── services/          # 业务逻辑层
│   ├── provisioner_service.py      # 节点初始化
│   ├── healer_service.py          # 节点自愈
│   ├── monitor.py                 # 哨兵监控
│   └── probe_*.py                 # 探针管理
│
├── infrastructure/    # 基础设施层
│   ├── aws/           # AWS 资源调度
│   └── cloudflare/    # DNS 管理
│
├── database/          # 数据访问层
│   ├── sqlite_manager.py    # SQLite 连接
│   └── *_repo.py            # 数据仓储
│
└── tests/             # 测试
    ├── unit/          # 单元测试
    ├── integration/   # 集成测试
    └── service/       # 服务层测试
```

---

## 调试检查清单

- [ ] 虚拟环境已激活
- [ ] `pip install -r requirements.txt` 已执行
- [ ] `config.yaml` 已正确配置
- [ ] 数据库文件存在或可创建
- [ ] 相关端口未被占用
- [ ] 日志级别已调整为 DEBUG
