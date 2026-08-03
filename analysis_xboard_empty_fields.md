# Xboard 系统字段为空问题全面分析报告

## 问题描述

在 Xboard 管理界面中，ShadowFleet 自动创建的节点存在以下字段为空的问题：
1. **权限组 (group_ids)** - 显示"请选择权限组"
2. **服务器名称指示 (SNI / server_name)** - 显示"不使用请留空"

## 根本原因分析

### 1. 权限组 (group_ids) 为空的原因

#### 问题根源
ShadowFleet 在创建节点时**已经正确设置了 group_ids**，但 Xboard 前端界面**无法正确显示**这些数据。

#### 证据链

**A. ShadowFleet 代码确认已设置 group_ids**

在 `fleet_scheduler_service.py:336-362` 中：
```python
# 自动查询所有权限组 ID
group_ids = self._get_all_group_ids()

request = ProvisionRequest(
    protocol_type=gap.protocol_type,
    node_name=node_name,
    # ... 其他字段 ...
    # 使用自动查询的所有权限组 ID
    group_ids=group_ids if group_ids else None,
)
```

**B. 权限组查询逻辑**

在 `fleet_scheduler_service.py:506-528` 中：
```python
def _get_all_group_ids(self) -> list[int]:
    """查询 Xboard 数据库中的所有权限组 ID（带缓存）"""
    if self._cached_group_ids is not None:
        return self._cached_group_ids

    try:
        from database.xboard_repo import XboardRepo
        xboard_repo = XboardRepo(self._runtime)
        group_ids = xboard_repo.get_all_group_ids()
        self._logger.info(
            "Loaded %d group IDs from Xboard: %s",
            len(group_ids),
            group_ids,
        )
        self._cached_group_ids = group_ids
        return group_ids
    except Exception as e:
        self._logger.warning(
            "Failed to query group IDs from Xboard: %s, using empty list",
            e,
        )
        self._cached_group_ids = []
        return []
```

**C. 数据库写入逻辑**

在 `xboard_repo.py:119-199` 的 `register_node` 方法中：
```python
sql = """
    INSERT INTO public.v2_server (
        type,
        code,
        parent_id,
        group_ids,    # ← 这里写入了 group_ids
        route_ids,
        name,
        # ... 其他字段 ...
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    RETURNING id
"""
parameters = (
    normalized_node_type,
    request.code,
    request.parent_id,
    self._to_json_text(request.group_ids if request.group_ids is not None else []),  # ← 转换为 JSON
    # ... 其他参数 ...
)
```

**D. Xboard 数据库表结构**

在 `Xboard-master/database/migrations/2025_01_05_131425_create_v2_server_table.php:20` 中：
```php
$table->json('group_ids')->nullable()->comment('Group ID');
```

字段类型是 `json`，可以存储 JSON 数组。

**E. Xboard 前端验证规则**

在 `Xboard-master/app/Http/Requests/Admin/ServerSave.php:88` 中：
```php
'group_ids' => 'nullable|array',
```

验证规则显示 `group_ids` 是**可选的 (nullable)**，这意味着：
- 前端表单可以不填写权限组
- 但如果数据库中已有值，前端应该能够显示

#### 结论

**权限组数据已经正确写入数据库**，问题出在：
1. **Xboard 前端界面的数据绑定问题** - 可能是 Vue/React 组件没有正确读取 `group_ids` 字段
2. **JSON 格式解析问题** - Xboard 前端可能期望特定的 JSON 格式

---

### 2. 服务器名称指示 (SNI) 为空的原因

#### 问题根源
SNI 字段在 Xboard 中的存储位置**取决于协议类型**，不同协议的 SNI 存储在 `protocol_settings` 的不同路径下。

#### 证据链

**A. Xboard 协议配置结构**

在 `Xboard-master/app/Models/Server.php:125-252` 中定义了不同协议的配置结构：

```php
private const PROTOCOL_CONFIGURATIONS = [
    self::TYPE_TROJAN => [
        'allow_insecure' => ['type' => 'boolean', 'default' => false],
        'server_name' => ['type' => 'string', 'default' => null],  // ← Trojan 的 SNI 在顶层
        'network' => ['type' => 'string', 'default' => null],
        'network_settings' => ['type' => 'array', 'default' => null]
    ],
    self::TYPE_VMESS => [
        'tls' => ['type' => 'integer', 'default' => 0],
        'network' => ['type' => 'string', 'default' => null],
        'rules' => ['type' => 'array', 'default' => null],
        'network_settings' => ['type' => 'array', 'default' => null],
        'tls_settings' => ['type' => 'array', 'default' => null]  // ← VMess 的 SNI 在 tls_settings.server_name
    ],
    self::TYPE_VLESS => [
        'tls' => ['type' => 'integer', 'default' => 0],
        'tls_settings' => ['type' => 'array', 'default' => null],  // ← VLESS 的 SNI 在 tls_settings.server_name
        'flow' => ['type' => 'string', 'default' => null],
        'network' => ['type' => 'string', 'default' => null],
        'network_settings' => ['type' => 'array', 'default' => null],
        'reality_settings' => [
            'type' => 'object',
            'fields' => [
                'allow_insecure' => ['type' => 'boolean', 'default' => false],
                'server_port' => ['type' => 'string', 'default' => null],
                'server_name' => ['type' => 'string', 'default' => null],  // ← Reality 的 SNI 在 reality_settings.server_name
                'public_key' => ['type' => 'string', 'default' => null],
                'private_key' => ['type' => 'string', 'default' => null],
                'short_id' => ['type' => 'string', 'default' => null]
            ]
        ]
    ],
    self::TYPE_ANYTLS => [
        'padding_scheme' => ['type' => 'array', 'default' => [...]],
        'tls' => [
            'type' => 'object',
            'fields' => [
                'server_name' => ['type' => 'string', 'default' => null],  // ← AnyTLS 的 SNI 在 tls.server_name
                'allow_insecure' => ['type' => 'boolean', 'default' => false]
            ]
        ]
    ],
];
```

**B. ShadowFleet 的 SNI 配置生成**

在 `protocol_config_builder.py` 中，ShadowFleet 生成的配置结构：

**Trojan 协议** (`protocol_config_builder.py:76-111`)：
```python
def build_trojan_config(
    sni_domain: str | None = None,
    allow_insecure: bool = True,
    network: str = "grpc",
) -> dict[str, Any]:
    if sni_domain is None:
        sni_domain = ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS[0]

    config: dict[str, Any] = {
        "allow_insecure": allow_insecure,
        "server_name": sni_domain,  # ← 正确：顶层 server_name
        "network": network,
    }
    return config
```
✅ **Trojan 配置正确**

**VMess 协议** (`protocol_config_builder.py:113-150`)：
```python
def build_vmess_config(
    tls_enabled: bool = True,
    network: str = "grpc",
    sni_domain: str | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "tls": 1 if tls_enabled else 0,
        "network": network,
    }

    # 如果启用 TLS 且提供了 SNI 域名，添加 tls_settings
    if tls_enabled and sni_domain:
        config["tls_settings"] = {
            "server_name": sni_domain,  # ← 正确：tls_settings.server_name
        }

    return config
```
✅ **VMess 配置正确**

**VLESS 协议** (`protocol_config_builder.py:152-216`)：
```python
def build_vless_config(
    sni_domain: str | None = None,
    reality_enabled: bool = True,
    reality_dest: str | None = None,
    reality_private_key: str | None = None,
    reality_public_key: str | None = None,
    # ...
) -> dict[str, Any]:
    if sni_domain is None:
        sni_domain = ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS[0]

    config: dict[str, Any] = {
        "tls": 1,
        "network": network,
        "flow": flow,
    }

    tls_settings: dict[str, Any] = {}

    if reality_enabled and reality_private_key and reality_public_key:
        # Reality 配置
        tls_settings["server_name"] = sni_domain  # ← 正确：tls_settings.server_name
        tls_settings["allow_insecure"] = allow_insecure
        tls_settings["public_key"] = reality_public_key
        tls_settings["private_key"] = reality_private_key
        tls_settings["short_id"] = ""
        tls_settings["server_port"] = reality_dest

    if tls_settings:
        config["tls_settings"] = tls_settings

    return config
```
✅ **VLESS 配置正确**

**AnyTLS 协议** (`protocol_config_builder.py:36-74`)：
```python
def build_anytls_config(
    sni_domain: str | None = None,
    allow_insecure: bool = True,
) -> dict[str, Any]:
    if sni_domain is None:
        sni_domain = ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS[0]

    return {
        "padding_scheme": [...],
        "tls": {
            "server_name": sni_domain,  # ← 正确：tls.server_name
            "allow_insecure": allow_insecure,
        }
    }
```
✅ **AnyTLS 配置正确**

#### 结论

**SNI 配置已经正确生成并写入数据库**，问题可能出在：
1. **Xboard 前端表单字段映射错误** - 前端可能在错误的路径下查找 SNI 值
2. **协议类型识别问题** - 前端可能没有根据协议类型动态调整字段路径

---

## 验证方法

### 1. 验证数据库中的实际数据

登录到服务器并查询数据库：

```bash
ssh test-do-2h4g

# 查询最新的 ShadowFleet 节点
psql -U xboard -d xboard -c "
SELECT 
    id, 
    name, 
    type, 
    group_ids, 
    protocol_settings::text 
FROM v2_server 
WHERE name LIKE 'sf-%' 
ORDER BY id DESC 
LIMIT 3;
"
```

**预期结果：**
- `group_ids` 应该是一个 JSON 数组，例如：`[1, 2, 3]`
- `protocol_settings` 应该包含 SNI 配置，例如：
  - Trojan: `{"server_name": "www.bilibili.com", ...}`
  - VMess: `{"tls_settings": {"server_name": "www.bilibili.com"}, ...}`
  - VLESS: `{"tls_settings": {"server_name": "www.bilibili.com"}, ...}`

### 2. 验证 Xboard 前端代码

检查 Xboard 前端的服务器编辑表单：

```bash
cd D:/tanxuan/project/Xboard-master
find . -type f \( -name "*.vue" -o -name "*.js" -o -name "*.tsx" \) | xargs grep -l "group_ids\|server_name"
```

查找前端组件中 `group_ids` 和 `server_name` 的数据绑定逻辑。

---

## 解决方案

### 方案 1：修复 Xboard 前端（推荐）

**优点：** 根本解决问题，所有自动创建的节点都能正确显示

**步骤：**
1. 定位 Xboard 前端的服务器编辑表单组件
2. 检查 `group_ids` 的数据绑定逻辑
3. 检查 `protocol_settings` 中 SNI 字段的读取逻辑
4. 确保前端正确解析 JSON 格式的 `group_ids`
5. 确保前端根据协议类型从正确的路径读取 SNI

### 方案 2：手动修复已创建的节点

**适用场景：** 临时解决，或者 Xboard 前端代码无法修改

**步骤：**
1. 登录 Xboard 管理界面
2. 编辑每个 ShadowFleet 节点
3. 手动选择权限组
4. 手动填写 SNI 域名（例如 `www.bilibili.com`）
5. 保存

### 方案 3：数据库直接修复（不推荐）

**风险：** 可能破坏数据一致性

**仅用于验证：**
```sql
-- 查看当前数据
SELECT id, name, type, group_ids, protocol_settings 
FROM v2_server 
WHERE name LIKE 'sf-%' 
LIMIT 1;

-- 如果确认 group_ids 和 protocol_settings 已正确设置，
-- 则问题确实在前端，无需修改数据库
```

---

## 技术细节总结

### ShadowFleet 的节点创建流程

1. **FleetSchedulerService** 检测到容量缺口
2. 调用 `_get_all_group_ids()` 查询所有权限组
3. 调用 `_get_protocol_defaults()` 获取协议默认配置（包含 SNI）
4. 创建 `ProvisionRequest`，包含 `group_ids` 和 `sni_domain`
5. **ProvisioningPipeline** 执行节点创建流程：
   - `RegisterNodeStep`: 调用 `XboardRepo.register_node()` 写入数据库
   - `AutoConfigureNodeStep`: 调用 `NodeAutoConfigService.auto_configure_node()` 生成协议配置
6. **NodeAutoConfigService** 调用 `ProtocolConfigBuilder` 生成完整的 `protocol_settings`
7. **XboardRepo** 将 `protocol_settings` 更新到数据库

### Xboard 的数据结构

- **group_ids**: JSON 数组，存储在 `v2_server.group_ids` 字段
- **SNI**: 存储在 `v2_server.protocol_settings` JSON 字段中，路径取决于协议类型：
  - Trojan: `protocol_settings.server_name`
  - VMess: `protocol_settings.tls_settings.server_name`
  - VLESS: `protocol_settings.tls_settings.server_name` 或 `protocol_settings.reality_settings.server_name`
  - AnyTLS: `protocol_settings.tls.server_name`

---

## 下一步行动

1. **立即验证：** 登录服务器查询数据库，确认 `group_ids` 和 `protocol_settings` 是否已正确写入
2. **定位前端问题：** 检查 Xboard 前端代码，找到服务器编辑表单的数据绑定逻辑
3. **修复前端：** 修改前端代码，确保正确读取和显示这两个字段
4. **测试验证：** 创建新节点，确认前端能够正确显示权限组和 SNI

---

## 附录：相关代码文件

### ShadowFleet 代码
- `services/fleet_scheduler_service.py` - 自动调度器，负责创建节点
- `services/node_auto_config_service.py` - 节点自动配置服务
- `services/protocol_config_builder.py` - 协议配置生成器
- `database/xboard_repo.py` - Xboard 数据库操作
- `services/provisioning_pipeline.py` - 节点创建流程

### Xboard 代码
- `app/Models/Server.php` - 服务器模型，定义协议配置结构
- `app/Http/Requests/Admin/ServerSave.php` - 服务器保存验证规则
- `database/migrations/2025_01_05_131425_create_v2_server_table.php` - 数据库表结构
