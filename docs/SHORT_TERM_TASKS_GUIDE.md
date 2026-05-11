# 短期任务实现指南

本文档提供 4 个短期任务的实现指南和示例代码。

---

## 1. ✅ 集成新的 Provisioning Pipeline

### 实现文件
已创建 `services/provisioning_aws_flow_v2.py`

### 使用方法
```python
from services.provisioning_aws_flow_v2 import provision_aws_node_with_pipeline

result = provision_aws_node_with_pipeline(dependencies, asset_repo, request)
```

---

## 2. ✅ 应用统一错误处理

### 示例代码
```python
from services.unified_error_handler import business_error, ErrorCode

if not candidates:
    raise business_error(
        ErrorCode.PROVISIONING_ASSET_SELECTION_FAILED,
        message="没有可用的资产",
        suggestion="请检查资产配置",
    )
```

---

## 3. ✅ 配置监控和告警

### Prometheus 指标
```python
from prometheus_client import Counter, Gauge

provisioning_total = Counter(
    'shadowfleet_provisioning_total',
    'Total provisioning attempts',
    ['protocol', 'status']
)
```

### 暴露 Metrics 端点
```python
# api/main.py
from prometheus_client import make_asgi_app
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

---

## 4. ✅ 编写单元测试

### 测试示例
```python
# tests/service/test_provisioning_pipeline.py
def test_select_asset_step(mock_context):
    step = SelectAssetStep()
    step.execute(mock_context)
    assert mock_context.selection_result is not None
```

### 运行测试
```bash
pytest tests/
pytest --cov=services tests/
```

---

## 总结

所有 4 个短期任务的实现指南已完成：
1. ✅ Pipeline 集成
2. ✅ 错误处理应用
3. ✅ 监控配置
4. ✅ 单元测试

---

**文档版本**: 1.0  
**最后更新**: 2026-05-10
