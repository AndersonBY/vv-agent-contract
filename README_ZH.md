# vv-agent-contract

`vv-agent-contract` 是 Python `vv-agent` 与 Rust `vv-agent-rs` 共同使用的、
语言无关的唯一契约源。

本仓库维护公共行为、canonical fixtures、wire schema、兼容性规则和采用
状态，不包含 Python 或 Rust 的运行时实现。

两个实现仓库通过 `contract.lock.json` 锁定精确的契约版本、Git revision、
release artifact SHA-256 和 fixture manifest SHA-256。fixture 会作为生成的
vendored snapshot 提交到实现仓库，因此本地和 CI 测试不依赖网络。

实现仓库不得直接编辑 vendored fixture。共享行为变化必须先修改本仓库，
再同步到本版 required implementations，由必需实现的真实 producer tests、
全量质量门禁和中央跨仓 CI 验证。

`support-matrix.json` 使用 schema 2，`required_implementations` 当前仅包含 Python。
契约 23.0.0 保持 verified；发布不等于采用，后续版本须由必需实现及中央 CI 通过后
才能标记 verified。

Rust 冻结于自己的契约 23.0.0 / 包系列 0.21.x，保留已验证的基线 revision。
仅允许安全、数据完整性、v23 正确性修复和不改变行为的依赖/构建维护；不增加新 kernel、
wire 或公共行为。Python 采用新契约不代表 Rust 支持该版本。重新启用 Rust 必须有
新的 Maker 决策，并完整采用届时的当前契约，通过真实 producer、全量门禁及中央 CI。

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
只入队的 Cycle 调度器与终态 controller 边界见
`docs/distributed-run-driver.md`。
统一的 durable controller command、host interaction、suspend、CAS fence、receipt
和恢复规则见 `docs/controller-command.md`。
可持久化 deferred tool 的 admission、resolution、批次 barrier 与恢复规则见
`docs/durable-deferred-tools.md`。
主循环与内部模型调用的完整计量、预算、事件和恢复规范见
`docs/model-call-accounting.md`。
类型化工具声明、累计元数据策略和执行生命周期遥测规范见
`docs/tool-metadata-and-telemetry.md`。
结构化提示词传播、provider 投影、有界工具结果、artifact/cursor 恢复、归档式
microcompaction 和当前工具面规范见
`docs/prompt-bundles-and-tool-results.md`。大小与哈希等恢复元数据只保留在宿主侧
类型化记录中；模型可见的 compact marker 仅包含工具名、artifact 路径、取回提示和
少量预览。canonical `Message.artifact_ref` 会在宿主持久化和分布式 round-trip 中
保留，但 provider/model 投影必须始终剔除该字段。
