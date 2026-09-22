<#
.SYNOPSIS
    FinanceAgent 一键启动：PostgreSQL / Redis 容器 + 后端 + Celery worker + 前端。

.DESCRIPTION
    按依赖顺序启动整套环境，并**在每一步真正就绪后才进入下一步**：

      1. 确保 Docker Desktop 已运行，并启动 postgres-prod / redis-prod 容器
      2. 用应用自身配置探测数据库与 Redis 可连接（不是只看端口通不通）
      3. 启动后端（uvicorn）
      4. 启动 Celery worker（量化计算，可用 -SkipCelery 跳过）
      5. 启动前端（vite dev server，可用 -SkipFrontend 跳过）

    脚本是幂等的：重复运行不会重复拉起已经在跑的服务，只会补齐缺失的部分。
    这正是为了避免"数据库还没就绪就先起了后端"导致的 connection timeout。

.PARAMETER BackendPort
    后端端口，默认 8000。

.PARAMETER FrontendPort
    前端端口，默认 5173（仅用于占用检测与提示）。

.PARAMETER SkipDocker
    跳过 Docker 与容器管理（数据库/Redis 已在别处运行时使用）。

.PARAMETER SkipCelery
    不启动 Celery worker（只用投顾对话、不做量化计算时可跳过）。

.PARAMETER SkipFrontend
    不启动前端（只调后端 API 或跑测试时使用）。

.PARAMETER TimeoutSeconds
    等待 Docker 与数据库就绪的秒数，默认 90。

.PARAMETER Reload
    以热重载模式启动后端（等价 uvicorn --reload），适合改代码即生效的开发场景。
    默认关闭：reloader 会额外创建子进程，分析线程运行时重启等待更久。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-all.ps1
    # 或直接双击 scripts\start-all.bat

.EXAMPLE
    .\scripts\start-all.ps1 -SkipCelery -SkipFrontend
    # 只起数据库 + 后端

.EXAMPLE
    .\scripts\start-all.ps1 -Reload
    # 后端带热重载
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$SkipDocker,
    [switch]$SkipCelery,
    [switch]$SkipFrontend,
    [switch]$Reload,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'

# ── 路径 ──────────────────────────────────────────────────────────
$RepoRoot    = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$VenvPython  = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$CeleryExe   = Join-Path $RepoRoot '.venv\Scripts\celery.exe'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$PG_CONTAINER = 'postgres-prod'
$REDIS_CONTAINER = 'redis-prod'

function Write-Step { param([string]$Text) Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "    [OK] $Text"   -ForegroundColor Green }
function Write-Warn2{ param([string]$Text) Write-Host "    [!]  $Text"   -ForegroundColor Yellow }
function Write-Err2 { param([string]$Text) Write-Host "    [X]  $Text"   -ForegroundColor Red }

function Test-PortInUse {
    param([int]$Port)
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$listening
}

function Start-InNewWindow {
    <#
      在独立窗口里启动命令，并保留窗口显示日志（-NoExit）。

      两点经验（都已实测）：

      1) 用 -EncodedCommand（UTF-16LE + Base64）传命令，而不是 -Command "..."。
         Start-Process 会把 -ArgumentList 数组用空格拼成一条命令行，内层引号被剥掉，
         于是工作目录里的空格（本项目路径含 "python project"）会破坏解析。

      2) 不要设置 $Host.UI.RawUI.WindowTitle，也不要用 cmd /c start + -WindowStyle Hidden。
         实测这两种写法会让子进程拿不到可用控制台，服务起不来。
    #>
    param([string]$Title, [string]$WorkDir, [string]$Command)

    $script = @"
Set-Location -LiteralPath '$WorkDir'
$Command
"@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
    Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoExit', '-NoLogo', '-EncodedCommand', $encoded) | Out-Null
}

# ── 前置检查 ──────────────────────────────────────────────────────
Write-Step '检查项目环境'

if (-not (Test-Path $VenvPython)) {
    Write-Err2 "未找到虚拟环境：$VenvPython"
    Write-Host '    请先创建并安装依赖：' -ForegroundColor Gray
    Write-Host '        python -m venv .venv' -ForegroundColor Gray
    Write-Host '        .venv\Scripts\pip install -r requirements.txt' -ForegroundColor Gray
    exit 1
}
Write-Ok "虚拟环境：$VenvPython"

$envFile = Join-Path $RepoRoot '.env'
if (-not (Test-Path $envFile)) {
    Write-Warn2 '.env 不存在，后端可能因缺少 DEEPSEEK_API_KEY 等配置启动失败'
} else {
    Write-Ok '.env 已找到'
}

# ── Docker 与容器 ─────────────────────────────────────────────────
$dockerReady = $SkipDocker
if (-not $SkipDocker) {
    Write-Step '确保 Docker 与 PostgreSQL / Redis 容器运行'

    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 'Docker 未运行，尝试启动 Docker Desktop ...'
        $dockerExe = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\frontend\Docker Desktop.exe'),
            (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1

        if ($dockerExe) {
            Start-Process $dockerExe | Out-Null
        } else {
            Write-Err2 '未找到 Docker Desktop，请手动启动后再运行本脚本'
            exit 1
        }

        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 3
            docker info *> $null
            if ($LASTEXITCODE -eq 0) { break }
            Write-Host '    等待 Docker 引擎就绪 ...' -ForegroundColor DarkGray
        }
        docker info *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Err2 "Docker 在 $TimeoutSeconds 秒内未就绪"
            exit 1
        }
    }
    Write-Ok 'Docker 引擎可用'

    foreach ($container in @($PG_CONTAINER, $REDIS_CONTAINER)) {
        $state = (docker inspect -f '{{.State.Running}}' $container 2>$null)
        if ($state -eq 'true') {
            Write-Ok "容器 $container 已在运行"
        } else {
            docker start $container *> $null
            if ($LASTEXITCODE -ne 0) {
                Write-Err2 "容器 $container 启动失败；它是否已创建？（docker ps -a 查看）"
                exit 1
            }
            Write-Ok "容器 $container 已启动"
        }
    }
    $dockerReady = $true
}

# ── 等待数据库与 Redis 真正可连接 ─────────────────────────────────
# 用应用自身的配置探测，而不是只测端口：能同时验证库名/密码/目标库是否正确。
# 这正是"端口通了但应用连不上"这类问题的分界线。
#
# 探测代码写成临时文件并通过 PYTHONPATH 指向项目根：`python -c` 传多行代码在
# Windows 命令行上会被破坏（换行被吞掉 → SyntaxError），而作为脚本文件运行时
# sys.path[0] 是脚本所在目录，必须靠 PYTHONPATH 才能 import finance_agent。
if ($dockerReady) {
    Write-Step '等待数据库与 Redis 就绪（用应用配置探测）'

    $probeFile = Join-Path $env:TEMP "finance_agent_readiness_$PID.py"
    @'
import sys

fail = []
try:
    from finance_agent.config import get_postgres_connection_factory
    conn = get_postgres_connection_factory()()
    conn.close()
except Exception as exc:
    fail.append("postgres/%s: %s" % (type(exc).__name__, exc))
try:
    import redis
    from finance_agent.config import REDIS_URL
    redis.from_url(REDIS_URL, socket_connect_timeout=3).ping()
except Exception as exc:
    fail.append("redis/%s: %s" % (type(exc).__name__, exc))

if fail:
    print(" | ".join(fail))
    sys.exit(1)
sys.exit(0)
'@ | Set-Content -Path $probeFile -Encoding UTF8

    # 原生命令写入 stderr 时，$ErrorActionPreference='Stop' 会把它当成终止错误，
    # 导致重试循环直接中断。这里临时降级，只依据退出码判断结果。
    $savedEap = $ErrorActionPreference
    $savedPythonPath = $env:PYTHONPATH
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $ready = $false
    $lastFail = ''
    try {
        $ErrorActionPreference = 'Continue'
        $env:PYTHONPATH = $RepoRoot
        while ((Get-Date) -lt $deadline) {
            $output = & $VenvPython $probeFile 2>&1
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            $lastFail = ($output | Where-Object { $_ } | Select-Object -Last 1)
            Write-Host "    等待中：$lastFail" -ForegroundColor DarkGray
            Start-Sleep -Seconds 3
        }
    } finally {
        $ErrorActionPreference = $savedEap
        $env:PYTHONPATH = $savedPythonPath
        Remove-Item $probeFile -Force -ErrorAction SilentlyContinue
    }

    if (-not $ready) {
        Write-Err2 "数据库/Redis 在 $TimeoutSeconds 秒内仍不可连接"
        if ($lastFail) { Write-Host "    最后错误：$lastFail" -ForegroundColor Red }
        Write-Host '    排查建议：' -ForegroundColor Gray
        Write-Host "        docker logs $PG_CONTAINER --tail 30" -ForegroundColor Gray
        Write-Host "        docker logs $REDIS_CONTAINER --tail 30" -ForegroundColor Gray
        exit 1
    }
    Write-Ok 'PostgreSQL 与 Redis 均可连接'
}

# ── 后端 ──────────────────────────────────────────────────────────
Write-Step "启动后端（端口 $BackendPort）"
if (Test-PortInUse -Port $BackendPort) {
    Write-Warn2 "端口 $BackendPort 已被占用，跳过后端启动（可能已在运行）"
} else {
    $reloadArg = if ($Reload) { ' --reload' } else { '' }
    Start-InNewWindow -Title 'FinanceAgent 后端' -WorkDir $RepoRoot `
        -Command "& '$VenvPython' -m uvicorn finance_agent.main:app --host 127.0.0.1 --port $BackendPort$reloadArg"
    # 不在这里宣称"已启动"：进程只是被拉起，是否真的服务要看下面的健康检查。
    Write-Host '    已在新窗口拉起后端，等待就绪 ...' -ForegroundColor DarkGray

    $deadline = (Get-Date).AddSeconds(60)
    $up = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/api/health" `
                -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { $up = $true; break }
        } catch {
            if (Test-PortInUse -Port $BackendPort) { $up = $true; break }
        }
    }
    if ($up) {
        $mode = if ($Reload) { '（热重载模式）' } else { '' }
        Write-Ok "后端已就绪$mode http://127.0.0.1:$BackendPort/api/health"
    } else {
        Write-Err2 "后端在 60 秒内未响应，启动可能失败"
        Write-Host '    请查看标题为「FinanceAgent 后端」的窗口中的错误信息' -ForegroundColor Gray
        exit 1
    }
}

# ── Celery worker ─────────────────────────────────────────────────
# Celery 不占固定端口，无法像后端/前端那样用端口判断是否已在运行，
# 因此按「命令行是否已有本项目 worker」判重：重复启动会出现多个 worker 争抢
# 同一个队列，导致量化任务被重复消费。
if (-not $SkipCelery) {
    Write-Step '启动 Celery worker（量化计算队列 finance.quant）'

    $existingWorkers = @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match 'finance_agent\.celery_app:celery_app' -and
        $_.CommandLine -match 'worker'
    })

    if ($existingWorkers.Count -gt 0) {
        Write-Warn2 "已有 $($existingWorkers.Count) 个 Celery worker 进程在运行，跳过启动"
    } elseif (Test-Path $CeleryExe) {
        Start-InNewWindow -Title 'FinanceAgent Celery' -WorkDir $RepoRoot `
            -Command "& '$CeleryExe' -A finance_agent.celery_app:celery_app worker -Q finance.quant -l info"
        Write-Ok 'Celery worker 已在独立窗口启动'
    } else {
        Write-Warn2 '未找到 celery，跳过（安装依赖后可用）'
    }
} else {
    Write-Host "`n==> 已按参数跳过 Celery worker" -ForegroundColor DarkGray
}

# ── 前端 ──────────────────────────────────────────────────────────
if (-not $SkipFrontend) {
    Write-Step "启动前端（端口 $FrontendPort）"
    if (Test-PortInUse -Port $FrontendPort) {
        Write-Warn2 "端口 $FrontendPort 已被占用，跳过前端启动（可能已在运行）"
    } elseif (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
        Write-Warn2 'frontend\node_modules 不存在，请先执行：cd frontend; npm install'
    } else {
        Start-InNewWindow -Title 'FinanceAgent 前端' -WorkDir $FrontendDir -Command 'npm run dev'
        Write-Host '    已在新窗口拉起前端，等待就绪 ...' -ForegroundColor DarkGray

        $deadline = (Get-Date).AddSeconds(60)
        $up = $false
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 2
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort/" `
                    -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
                if ($resp.StatusCode -eq 200) { $up = $true; break }
            } catch {
                if (Test-PortInUse -Port $FrontendPort) { $up = $true; break }
            }
        }
        if ($up) {
            Write-Ok "前端已就绪 http://localhost:$FrontendPort"
        } else {
            Write-Err2 "前端在 60 秒内未响应，启动可能失败"
            Write-Host '    请查看标题为「FinanceAgent 前端」的窗口中的错误信息' -ForegroundColor Gray
            exit 1
        }
    }
} else {
    Write-Host "`n==> 已按参数跳过前端" -ForegroundColor DarkGray
}

# ── 汇总 ──────────────────────────────────────────────────────────
Write-Host "`n================ 启动完成 ================" -ForegroundColor Green
Write-Host "  前端页面    http://localhost:$FrontendPort"          -ForegroundColor White
Write-Host "  后端接口    http://127.0.0.1:$BackendPort"          -ForegroundColor White
Write-Host "  接口文档    http://127.0.0.1:$BackendPort/docs"     -ForegroundColor White
Write-Host "  健康检查    http://127.0.0.1:$BackendPort/api/health" -ForegroundColor White
Write-Host "  停止全部    powershell -ExecutionPolicy Bypass -File scripts\stop-all.ps1" -ForegroundColor Gray
Write-Host "==========================================" -ForegroundColor Green
Write-Host ''
