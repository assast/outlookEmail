# Apple 协议样本

`protocol.json` 是基于固定参考版本整理的**合成样本**，不是实际账户抓包。所有地址、密码、Cookie/SCNT/令牌示意值均为测试数据；不能用于登录 Apple。

- 来源：`t508708/icloud-mail@a2b952c2b50992c15f0f54dff23a15a234189a50`，`internal/apple/`，MIT（见仓库 `third_party/icloud-mail-LICENSE.txt`）。
- `vector` 的 A、B、派生密钥、m1/m2 来自该版本 `srp_test.go` 的固定 Node 向量，不由被测 Python 实现生成。
- `challenge` 按 `signin/init` 的 base64 结构编码该向量。`regions` 列出两区的独立 Web 端点；IDMSA/Account 端点是全球端点。
- `web_directory` 是可作为权威快照的 HME 格式；`account_directory` 是补充视图，即使空列表也不能用来撤下缺项。
- 测试内合成 409 待验证、验证码 payload、Web DSID/服务发现恢复、Account token TTL/API key 恢复及安全错误。它们测试协议契约与身份边界，不测试实际 HTTP 传输、Apple 认证、数据库或调度。

运行：

```sh
python -m pytest -q tests/test_icloud_srp.py tests/test_icloud_protocol.py
```

真实登录、双重验证、目录读取、续期和长期观察仍须使用有权使用的账号另行验收，不能由本目录样本代替。
