# vv-agent-contract

`vv-agent-contract` 是 Python `vv-agent` 与 Rust `vv-agent-rs` 共同使用的、
语言无关的唯一契约源。

本仓库维护公共行为、canonical fixtures、wire schema、兼容性规则和采用
状态，不包含 Python 或 Rust 的运行时实现。

两个实现仓库通过 `contract.lock.json` 锁定精确的契约版本、Git revision、
release artifact SHA-256 和 fixture manifest SHA-256。fixture 会作为生成的
vendored snapshot 提交到实现仓库，因此本地和 CI 测试不依赖网络。

实现仓库不得直接编辑 vendored fixture。共享行为变化必须先修改本仓库，
再同步到 Python 和 Rust，最后由两侧真实 producer tests 和中央跨仓 CI 验证。

```bash
python3 scripts/contractctl.py validate
node scripts/verify_jcs.mjs
python3 -m unittest discover -s tests
python3 scripts/contractctl.py build --output-dir dist
```

完整流程见 `docs/change-workflow.md`，版本规则见
`docs/versioning-policy.md`。
可选运行资源预算的规范见 `docs/run-budgets.md`。
可选的持久化恢复、操作日志与显式歧义处理规范见
`docs/checkpoint-resume.md`。
主循环与内部模型调用的完整计量、预算、事件和恢复规范见
`docs/model-call-accounting.md`。
类型化工具声明、累计元数据策略和执行生命周期遥测规范见
`docs/tool-metadata-and-telemetry.md`。
