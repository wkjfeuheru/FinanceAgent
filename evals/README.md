# 编排层评测与基准（evals/）

本目录是一组**离线可复现**的评测脚本，用于量化编排层的加固能力（意图路由、
并发扇出、故障降级）。与 `tests/` 的区别：`tests/` 断言单点契约，这里衡量
端到端的**效果指标**，产出的数字可直接引用到设计文档、周报或简历。

所有脚本默认不发起网络请求（内存桩替代模型与数据源），可纳入 CI。
`evals/` 不在 `pytest testpaths` 内，不会被测试用例收集。

## 一键运行

```bash
.venv/Scripts/python.exe -m evals.run_all
```

依次运行三个脚本，打印汇总指标，并写入 `evals/results/summary.json`。

Windows 下也可用脚本封装（会自动做基线校验）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-evals.ps1
# 或双击 scripts\run-evals.bat
```

## 回归基线（CI 门禁）

`evals/check_baseline.py` 读取 `summary.json`，对关键指标做阈值断言，任一跌破即
非零退出：

```bash
.venv/Scripts/python.exe -m evals.check_baseline
```

阈值取实测值的**保守下界**（留足机器抖动与数据源波动余量），定义在
`check_baseline.py` 的 `THRESHOLDS` 中：加固后路由正确率 ≥ 0.90、噪声子集 ≥ 0.75、
4 领域扇出加速比 ≥ 2.50、主模型故障下降级链成功率 = 1.0，另加两项布尔不变量
（依赖顺序保持、熔断降级全部由备用源完成）。调整语料后若阈值不再适用，显式改
`THRESHOLDS`，不要放宽到失去意义。

CI 配置见 [`.github/workflows/evals.yml`](../.github/workflows/evals.yml)：每次 push /
PR 跑评测 + 基线校验，并另行运行 `pytest`。

## 脚本清单

| 脚本 | 衡量什么 | 关键结论（实测样例） |
| --- | --- | --- |
| `intent_routing_eval` | 意图分类 → 领域路由正确率，含「模型输出含格式瑕疵」的噪声子集，并与**未加固的严格基线**做消融对照 | 加固后 30/30 = 100%；严格基线 21/30 = 70%；噪声子集 8/8 = 100% vs 基线 1/8 = 12.5% |
| `plan_fanout_benchmark` | 跨领域计划 `Send` 扇出 vs 串行执行器、多标的取数并行 vs 顺序的墙钟加速比；另验证带依赖 DAG 的依赖顺序不被并发破坏 | 4 领域扇出 3.93x；10 标的取数 4.98x；依赖顺序保持 |
| `degradation_fault_injection` | 主模型故障下的意图主备降级成功率；数据源故障下的熔断降级与半开探测 | 主模型四类故障降级链成功率 100%（无链 0%）；首选源故障时请求 10/10 由备用源完成 |

## 单独运行

```bash
.venv/Scripts/python.exe -m evals.intent_routing_eval            # 离线回放
.venv/Scripts/python.exe -m evals.intent_routing_eval --live     # 额外跑真实模型
.venv/Scripts/python.exe -m evals.plan_fanout_benchmark --repeats 7
.venv/Scripts/python.exe -m evals.degradation_fault_injection --verbose
```

结构化结果落在 `evals/results/*.json`（已在 `.gitignore` 中，可随时重生成）。

## 设计说明：为什么这是「加固能力」而非「模型能力」评测

`intent_routing_eval` 的离线回放**不绕过真实代码路径**：它把固定 payload 通过
真实 `DeepSeekIntentClassifier.classify`（含 JSON 解析与逐字证据校验）与真实
`classify_domains` 路由表喂进当前代码，因此回放结果与线上一致。噪声子集的
payload（`execution_mode` 误填进 `intent`、兄弟条目举证失败、低置信度、臆造
意图）正是线上真实出现过的模型输出形态，用来验证这些瑕疵是否被自动纠正而非
拖垮整批路由。严格基线则是「加固前」的语义，作为消融对照。

`--live` 模式会调用配置中的真实意图模型，仅覆盖 clean 用例，用于观察模型裸
准确率；需要 API key 与网络，失败不影响离线结论。
