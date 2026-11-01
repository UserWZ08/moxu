# 未来局域网接入边界

本版本不监听网络端口。`remote_contract.normalize_request` 是已实现的本地适配入口：校验版本、请求键、上传文件边界，返回待本机确认的草稿。它不是远程打印服务。

未来 HTTP 服务建议提供：

- `POST /v1/uploads`：认证后接收文件，限制大小及数量，返回 upload_id。
- `POST /v1/orders`：接收下方请求；持久化幂等键，重复请求返回同一订单，进入本机待确认列表。
- `GET /v1/orders/{id}`：返回状态与已提交份数。
- `GET /v1/capabilities`：返回允许的打印组合与价格，不暴露本机路径。

```json
{
  "version": "v1",
  "idempotency_key": "customer-device-unique-request-001",
  "community": "示例小区",
  "building": "1栋",
  "files": [{"upload_id": "uploaded-unique.pdf"}],
  "options": {"paper":"A4", "color":"黑白", "duplex":"双面长边", "copies":1, "dpi":600}
}
```

实现服务时需补齐设备配对、访问令牌、限额、文件扫描、超时清理、订单幂等存储与本机确认队列。禁止把客户端提交的任意路径或命令作为系统调用参数。文件上传暂存区应与原始文件隔离；所有订单仍须走相同的页数、计价、能力及状态逻辑。
