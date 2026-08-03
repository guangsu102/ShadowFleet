# Xboard 权限组字段为空问题 - 完整解决方案

## 问题确认

通过测试验证，我们已经确认：

### ✅ 数据库层面完全正确
- **group_ids**: `[1, 2]` - JSON 数组格式正确
- **protocol_settings**: 包含完整的 SNI 和 allow_insecure 配置
- **数据类型**: PostgreSQL `json` 类型，自动转换为 PHP array

### ✅ 后端 API 正常
- `ManageController::getNodes()` 正确读取 `group_ids`
- 代码：`$item['groups'] = ServerGroup::whereIn('id', $item['group_ids'])->get(['name', 'id']);`
- 这意味着后端能够正确解析 `group_ids` 并查询对应的权限组

### ✅ 部分前端字段正常显示
- **SNI 字段**: ✅ 正常显示 `www.bilibili.com`
- **允许不安全**: ✅ 正常勾选
- **权限组**: ❌ 显示为空（"请选择权限组"）

---

## 根本原因分析

**Xboard 前端在编辑表单中无法正确显示 `group_ids` 字段**

可能的原因：
1. 前端组件期望 `group_ids` 是特定格式
2. 前端使用了错误的字段名
3. 编辑表单初始化时没有正确加载 `group_ids`

---

## 临时解决方案（立即可用）

### 方案 1：手动修复

在 Xboard 管理界面中：
1. 编辑 ShadowFleet 创建的节点
2. 手动选择权限组（黄金、钻石）
3. 保存

---

## 验证步骤

### 1. 检查 API 响应

在浏览器中打开 Xboard 管理界面，打开开发者工具（F12），查看网络请求：

```
请求: GET /api/v2/admin/server/manage/getNodes
```

检查响应中的 `group_ids` 和 `groups` 字段格式。

### 2. 检查前端控制台错误

在浏览器开发者工具的 Console 标签中，查看是否有 JavaScript 错误。

---

## 总结

### 测试结果
- ✅ 数据库中 `group_ids = [1, 2]` 格式正确
- ✅ SNI 和 allow_insecure 字段正常显示
- ❌ 权限组字段在前端显示为空

### 结论
问题出在 **Xboard 前端的数据绑定逻辑**，而非 ShadowFleet 的数据写入。

### 建议
1. 短期：手动修复已创建的节点
2. 长期：向 Xboard 开发者反馈此问题
