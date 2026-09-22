<#
.SYNOPSIS
    运行编排层评测与基准，并做基线回归校验。

.DESCRIPTION
    依次执行 evals/ 下的三个离线评测，打印汇总指标，再按阈值做回归校验：

      1. intent_routing_eval      —— 意图分类 → 领域路由正确率（含噪声消融对照）
      2. plan_fanout_benchmark    —— 跨领域 Send 扇出 / 多标的取数的并发加速比
      3. degradation_fault_injection —— 意图主备降级 + 数据源熔断故障注入

    三个脚本默认**离线运行**（内存桩替代模型与数据源），不发网络请求，可纳入 CI。
    结构化结果落在 evals/results/*.json（已被 .gitignore 忽略，可随时重生成）。

    任一指标跌破 evals/check_baseline.py 中的阈值时脚本以非零码退出，用于拦住
    「加固能力退化」的提交。

.PARAMETER Json
    汇总结果输出路径，默认 evals/results/summary.json。

.PARAMETER SkipBaseline
    只跑评测、不做阈值校验（例如语料仍在调整、指标暂时低于阈值时）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run-evals.ps1
    # 或双击 scripts\run-evals.bat

.EXAMPLE
    .\scripts\run-evals.ps1 -SkipBaseline
    # 只看指标，不做回归判定
#>
[CmdletBinding()]
param(
    [string]$Json = 'evals/results/summary.json',
    [switch]$SkipBaseline
)

$ErrorActionPreference = 'Stop'

$RepoRoot   = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'

function Write-Step { param([string]$Text) Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "    [OK] $Text"   -ForegroundColor Green }
function Write-Err2 { param([string]$Text) Write-Host "    [X]  $Text"   -ForegroundColor Red }

if (-not (Test-Path $VenvPython)) {
    Write-Err2 "未找到虚拟环境：$VenvPython"
    Write-Host '    请先创建并安装依赖：python -m venv .venv; .venv\Scripts\pip install -e ".[dev]"' -ForegroundColor Gray
    exit 1
}

# 评测脚本通过 `-m evals.*` 运行，需要仓库根在 sys.path 上。
$savedPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $RepoRoot
$pushed = $false
try {
    Push-Location $RepoRoot
    $pushed = $true

    Write-Step '运行编排层评测（离线，不访问网络）'
    & $VenvPython -m evals.run_all
    if ($LASTEXITCODE -ne 0) {
        Write-Err2 "评测执行失败（exit $LASTEXITCODE）"
        exit $LASTEXITCODE
    }
    Write-Ok "评测完成，指标见上方汇总；明细写入 $Json"
} finally {
    if ($pushed) { Pop-Location }
    $env:PYTHONPATH = $savedPythonPath
}

if (-not $SkipBaseline) {
    Write-Step '基线回归校验'
    & $VenvPython -m evals.check_baseline --summary $Json
    if ($LASTEXITCODE -ne 0) {
        Write-Err2 '有指标跌破阈值，详见上方 [FAIL] 行。'
        exit 1
    }
    Write-Ok '所有关键指标均在阈值之上'
} else {
    Write-Host "`n==> 已按参数跳过基线校验" -ForegroundColor DarkGray
}

Write-Host "`n================ 评测完成 ================" -ForegroundColor Green
Write-Host "  汇总结果    $Json" -ForegroundColor White
Write-Host "  单项明细    evals/results/*.json" -ForegroundColor White
Write-Host "==========================================" -ForegroundColor Green
Write-Host ''
