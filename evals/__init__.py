"""编排层评测与基准脚本集合。

这些脚本衡量的是**编排层加固能力**而非模型裸能力，全部默认离线运行
（内存桩替代网络），可复现、可纳入 CI。以模块方式运行，例如：

    .venv/Scripts/python.exe -m evals.runners.intent_routing_eval
    .venv/Scripts/python.exe -m evals.runners.fanout_benchmark
    .venv/Scripts/python.exe -m evals.runners.degradation_fault_injection

报告输出到 stdout，结构化结果落到 ``.cache/evals/results/*.json``。
"""
