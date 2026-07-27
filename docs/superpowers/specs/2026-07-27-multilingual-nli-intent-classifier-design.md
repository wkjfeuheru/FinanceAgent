# 多语言 NLI 零样本意图分类器设计

## 目标

使用 `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` 替换项目中自行微调的中文 RoBERTa/ONNX 意图分类器。新实现通过 Hugging Face Transformers 的 `zero-shot-classification` 流水线完成中文多标签分类，不再维护训练数据生成、微调、阈值校准和 ONNX 导出流程。

本次只替换意图分类。Supervisor 的任务计划映射、确定性规则、子句切分、理财闲聊生成和工具调用保持原有职责。

## 意图与标签

运行时继续输出以下稳定的内部意图标识：

- `market_query`
- `stock_recommendation`
- `asset_allocation`
- `casual_chat`

NLI 模型接收描述完整业务语义的中文候选标签，而不是内部英文枚举：

| 内部标识 | 中文候选标签 |
| --- | --- |
| `market_query` | 查询股票、指数、板块或市场行情 |
| `stock_recommendation` | 推荐股票或判断某只股票是否值得买入 |
| `asset_allocation` | 根据金额、期限和风险偏好制定资产配置方案 |
| `casual_chat` | 一般理财知识、投资心态或非任务型金融交流 |

推理使用 `multi_label=True`，并使用中文假设模板 `这段用户消息的意图是{}。`。模型返回的候选标签会映射回内部标识，因此聊天 API、共享状态和任务计划接口不变。

## 运行时架构

新增零样本分类器封装，负责模型懒加载、输入构造、分数归一化和内部标签映射。输入由当前消息、截断后的近期上下文及 `pending_allocation` 状态组成。最大输入长度由配置控制。

分类流程如下：

1. 按现有标点和连接词规则拆分子句。
2. 分别对完整消息和各子句执行多标签零样本分类。
3. 子句超过对应标签阈值时，将该子句作为该意图的 `query`。
4. 只有完整消息命中时，将完整原文作为 `query`。
5. 合并重复标签和同类子句。
6. 使用现有确定性规则补充明显遗漏，特别是等待资产配置参数时的金额、期限和风险等级短回复。
7. 模型加载或推理异常时只使用规则结果，不回退到分类 LLM，也不阻断请求。

`finance_related` 不再作为模型候选意图。它根据四类金融意图命中情况和现有金融关键词规则计算，避免把辅助标签与业务意图放入同一次零样本竞争。

## 配置与上线模式

配置项调整为：

- `INTENT_CLASSIFIER_MODE=shadow|zero_shot|llm`
- `INTENT_ZERO_SHOT_MODEL=MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`
- `INTENT_MODEL_CACHE_DIR`：可选的预下载模型或 Hugging Face 缓存目录
- `INTENT_MAX_LENGTH=256`
- `INTENT_SCORE_THRESHOLD`：统一初始阈值，默认通过测试确定保守值
- `INTENT_DEVICE=-1`：默认 CPU

`shadow` 模式继续使用现有 LLM 分类结果驱动工作流，同时记录零样本结果、耗时、标签差异和规则补充情况。`zero_shot` 模式使用 NLI 结果驱动工作流且不调用分类 LLM。`llm` 模式作为显式兼容模式保留，方便影子评估期间对照；它不是零样本推理失败时的自动降级路径。

对外 `intent_source` 扩展为 `zero_shot`、`zero_shot+rule` 和 `rule_fallback`。影子预测只进入结构化日志，不进入 API 响应。

## 模型交付与依赖

开发环境允许 Transformers 首次启动时从 Hugging Face 下载模型。生产部署必须在构建或发布阶段预下载模型，并通过本地缓存目录加载，避免请求期间访问外网。

保留运行依赖 `transformers` 和模型推理所需的 PyTorch。删除自行微调专用的 `scikit-learn`、`accelerate`、`onnx`、`onnxscript`、`onnxruntime` 依赖，以及原训练、数据生成、人工复核整理、阈值校准、影子评估和 ONNX 导出脚本。若某个依赖仍被项目其他模块使用，则以全仓依赖搜索结果为准保留。

## 删除范围

删除或替换以下旧 RoBERTa 专用内容：

- 原 `BertIntentClassifier` ONNX 加载及 tokenizer 产物读取逻辑
- `scripts/train_intent_classifier.py`
- `scripts/generate_intent_dataset.py`
- `scripts/finalize_pending_intent_dataset.py`
- 依赖旧模型输出格式的影子评估脚本
- `intent-train` 可选依赖组及 ONNX Runtime 运行依赖
- README 和配置样例中的本地微调、导出与训练说明
- 旧 BERT 命名的测试和配置变量

不会删除用户生成的数据集或模型文件，除非它们明确位于版本控制内且仅属于旧流程；未跟踪的大型产物由用户自行确认后再清理。

## 测试策略

采用测试先行方式覆盖：

- 中文候选标签、中文假设模板和 `multi_label=True` 参数正确传入流水线
- 单标签和多标签结果映射为稳定内部意图
- 整句与子句分类合并、重复标签合并和原文回退
- `pending_allocation` 短回复由规则补充
- 模型加载失败、推理异常时返回 `rule_fallback`
- `zero_shot` 模式不调用分类 LLM
- `shadow` 模式不改变原工作流响应
- 理财闲聊仍由独立生成模型处理
- 删除旧脚本后不存在旧 RoBERTa/ONNX 配置及运行引用

测试使用注入的假流水线，不下载真实模型。另提供一个显式运行的集成检查，用于已预下载模型环境中的中文样例验证，但不纳入默认单元测试。

## 验收标准

- 默认测试套件通过。
- 聊天 API 请求和响应结构兼容。
- `zero_shot` 模式的意图分类不调用 DeepSeek。
- 模型不可用时请求仍可由规则路径完成。
- 仓库不再包含原 RoBERTa 微调和 ONNX 导出代码。
- 生产部署文档明确要求预下载模型，并说明切换 `shadow` 到 `zero_shot` 的步骤。

