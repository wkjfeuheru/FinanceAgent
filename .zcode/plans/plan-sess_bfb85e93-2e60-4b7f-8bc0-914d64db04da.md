# 完善 analysis_type 槽位：评级按选定维度收窄 + 删除 indicators 死字段

## 语义定义（本次确立的口径）

`analysis_type ∈ {fundamental, technical, both}`，默认 `both`。**风险维度始终强制纳入**（安全门禁，且只需 K 线即可算）。加权口径：

| 模式 | 参与加权的维度 | 分母 |
|---|---|---|
| both | 基本面 + 技术面 + 风险（+适配度） | 0.45+0.25+0.20=0.90（+0.10） |
| fundamental | 基本面 + 风险（+适配度） | 0.45+0.20=0.65（+0.10） |
| technical | 技术面 + 风险（+适配度） | 0.25+0.20=0.45（+0.10） |

**关键不变量**：必须区分「用户排除该维度」与「该维度数据缺失」。
- 被排除的维度：完全不参与加权，且**不再报该维度的缺失限制**（不制造噪音）。
- 被选定但取不到数据的维度：总分仍为 None → `数据不足`（**保住现有 `test_no_silent_fallbacks` 护栏**，不让缺失静默降级）。
- 风险维度任何模式下都按今天的算法（含"负增长/高 PE 拉低风险分"的两处惩罚）——**风险分数在三种模式下含义完全一致**，不因模式而变松。

## 后端改动

### 1. `finance_agent/research/contracts.py`
- `AnalysisRequest` 新增 `analysis_type: Literal["fundamental", "technical", "both"] = "both"`。
- **删除** `indicators: list[str]` 字段（已死的 AnalysisRequest 字段）。
- `frozen=True` / `extra="forbid"` 保留；`for_security` 用 `model_copy(update=...)` 自动保留新字段，无需改动。

### 2. `finance_agent/research/request_parser.py`
- `parse_analysis_request` 读取并校验 `analysis_type`：`_choice(slots.get("analysis_type"), [...], "both")`（非法值回落 both）。传参处删掉 `indicators=`，改为 `analysis_type=...`。
- **删除** `_normalize_indicators` 与 `_INDICATOR_ALIASES`（移除 indicators 后成为死代码）。

### 3. `finance_agent/research/rule_engine.py`（收窄核心，且**不触碰** snapshot/scoring/证据层）
- 新增 `_DIMENSION_SETS` 与 `_selected_dimensions(request)`。
- `evaluate`：
  - `fundamental = ... if "fundamental" in selected else None`；`technical = ... if "technical" in selected else None`；`risk` 照常计算。
  - 扩展 `score_restrictions` 之后，若 `"fundamental" not in selected`，过滤掉 `fundamental*` 前缀的评分级限制码（质量门禁的 warnings 保留，因为那是数据完整性披露）。
- `_weighted_total(fundamental, technical, risk, suitability, selected)`：只把「选定维度 + 风险」计入 required 集合；选定维度缺失 → None。suitability 逻辑不变。
- `_decide_action` 不改（它只是看到被收窄的 total；risk 门禁仍在最前）。

### 4. `finance_agent/research/narrative.py`
- 读 `result.request.analysis_type`；**仅当 != both** 时插入一句 `分析维度：技术面（风险始终纳入）。`。默认 both 时文本完全不变（保住 `test_research_narrative.py:30` 的子串断言）。
- `_score_items` 已有"None 不展示"逻辑 → 收窄后自然只列选定维度 + 风险（+适配度/综合），无需改。

### 5. `finance_agent/agents/stock_analysis.py`
- `_representative_request`：删除 `indicators=list(request.indicators)`，改为 `analysis_type=request.analysis_type`。
- `_compute_technical_indicators(stock_data, codes, analysis_type="both")`：新增默认参；`analysis_type == "fundamental"` 时直接返回 `{}`（"只看基本面"不展示技术面板，与语义一致）。默认值保证既有 `test_technical_indicators.py` 直接调用不受影响。
- `run_resolved` 调用处传 `request.analysis_type`。
- `_request_from_codes` / `handle_single_stock` 构造的请求走默认 both（无槽位来源），符合现状。

### 6. `finance_agent/orchestrator/slots.py`（让槽位在 LLM 抽取失败时也不丢）
- `_deterministic_extract` 的 stock_analysis 分支新增 `_extract_analysis_type(message)`：**仅在出现显式排他词**（只看/仅看/单看/只做/仅做/只分析/仅分析）时收窄——命中技术面词 → technical，命中基本面词 → fundamental，两者都命中 → both；无排他词一律留空（用默认 both）。
- 依据：避免把"分析一下它的行情和基本面"这类描述性语句误判为收窄（保住 `test_slot_extraction.py:107` 期望的 both），只在用户明确表达"只看某面"时才生效。

## 前端改动

### 7. `frontend/src/types/index.ts`
- `ResearchAnalysisResult.request` 类型补 `analysis_type?: 'fundamental' | 'technical' | 'both'`。

### 8. `frontend/src/components/MessageList.vue`
- 研究结论卡片标题行加维度徽标：当 `result.request?.analysis_type` 为 `fundamental`/`technical` 时显示「基本面视角」/「技术面视角」（both 不显示）。
- 分数区不用改：`scoreEntries` 已按非空展示，收窄后自动只显示选定维度。
- 技术指标面板在 fundamental 模式下后端返回空 → 自然不渲染。

## 测试

**更新**
- `tests/test_research_request_parser.py`：删掉 `indicators == ["MACD"]` 用例；新增 analysis_type 读取/默认/非法回落用例。

**新增**
- 规则引擎收窄数学：fundamental 模式按 (0.45+0.20) 归一；technical 模式按 (0.25+0.20) 归一；且默认 both 与今天完全一致（复算 `test_no_silent_fallbacks` 的 0.90 期望）。
- 护栏：选定维度数据缺失 → `数据不足`（不静默降级）；被排除维度的缺失限制码被过滤。
- narrative：收窄时出现「分析维度」句；both 时文本不含该句。
- 槽位：显式"只看技术面"→ technical；"只看基本面"→ fundamental；纯描述句仍 both。
- agent：analysis_type=technical 时 fundamental 分为 None；fundamental 时 `technical_analysis == {}`。

## 验证
1. `python -m compileall -q finance_agent`
2. 全量 `pytest`（当前 367 passed；确认 both 默认路径零回归）
3. 前端 `npm run build`（vue-tsc 类型检查）
4. 用临时预览入口真实渲染三种模式各截图核对（沿用上次做法，核对后清理临时文件）
5. `grep` 确认 `indicators` 字段在契约/解析器中零残留

## 明确不做（保持范围）
- `stock_recommendation` 不新增 analysis_type 槽位（本次只完善现有 `stock_analysis` 槽位）。
- 不做"双评级"（用户已选单一收窄口径）。
- `horizon` 字段维持现状（本次只清理 `indicators`）。
- 不做 git 提交（未获指示）。