# 编排层评测与基准

评测目录按 `scenarios/`、`runners/`、`baselines/` 分层。离线评测默认使用内存替身，
不发起网络请求，可纳入 CI。真实模型联网模式需显式传入 `--live`。

## 目录职责

- `scenarios/`：评测输入和场景说明。
- `runners/`：可执行评测、基线快照和汇总脚本。
- `baselines/`：版本化的回归阈值配置。
- `.cache/evals/results/`：运行时生成的 JSON 结果，受 `.gitignore` 忽略。

## 一键运行

```bash
.venv/Scripts/python.exe -m evals.runners.run_all
.venv/Scripts/python.exe -m evals.runners.check_baseline
```

`run_all` 依次运行意图路由、计划扇出和故障降级评测，并写入
`.cache/evals/results/summary.json`。基线门槛定义在
`evals/baselines/thresholds.json`：路由正确率至少 0.90，噪声子集至少 0.75，
四领域扇出加速比至少 2.50，主模型故障时降级链成功率为 1.0；依赖顺序和熔断
降级结果也会按布尔不变量校验。

Windows 可用封装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-evals.ps1
```

## 单独运行

```bash
.venv/Scripts/python.exe -m evals.runners.intent_routing_eval
.venv/Scripts/python.exe -m evals.runners.intent_routing_eval --live
.venv/Scripts/python.exe -m evals.runners.fanout_benchmark --repeats 7
.venv/Scripts/python.exe -m evals.runners.degradation_fault_injection --verbose
```

行为快照使用固定夹具和桩数据：

```bash
.venv/Scripts/python.exe -m evals.runners.baseline_snapshot > .cache/baseline.json
```

CI 配置位于 `.github/workflows/evals.yml`。
