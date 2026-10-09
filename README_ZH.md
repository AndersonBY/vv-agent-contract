# vv-agent-contract

语言无关的公共行为、canonical fixtures 和严格 wire schema 契约。当前 24.0.1
采用统一 session log/inbox kernel；Python F3 adoption 与中央 CI 尚待完成，状态为
pending-adoption。Rust 冻结于已验证的 23.0.0 / 0.21.x，不声明 v24 支持。

实现通过 contract.lock.json 锁定精确版本、revision、artifact 与 manifest 摘要；
vendored snapshot 只能由同步脚本生成。共享行为先在本仓库定义，再由真实 producer
与质量门禁证明。HEAD 只保留一个当前形状，Git 保存历史。

```bash
python3 scripts/contractctl.py validate
node scripts/verify_jcs.mjs
python3 -m unittest discover -s tests
python3 scripts/contractctl.py build --output-dir dist
```

- [Parity](docs/parity-contract.md)
- [Session kernel](docs/session-kernel.md)
- [Consumers and projections](docs/session-consumers.md)
- [App Server](docs/session-kernel.md#app-server)
- [Model accounting](docs/model-call-accounting.md)
- [Budgets](docs/run-budgets.md)
- [Prompts and tool recovery](docs/prompt-bundles-and-tool-results.md)
- [Tool metadata](docs/tool-metadata-and-telemetry.md)
- [Authoring and adoption](docs/change-workflow.md)
- [Version policy](docs/versioning-policy.md)
