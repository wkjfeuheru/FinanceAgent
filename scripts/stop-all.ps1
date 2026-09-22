<#
.SYNOPSIS
    停止 FinanceAgent 的应用进程（后端 / Celery / 前端）。

.DESCRIPTION
    默认只停**应用进程**，保留 PostgreSQL 与 Redis 容器：
    停掉数据库既没必要也容易让人以为数据丢了，下次启动还得重新等它就绪。
    需要连容器一起停时加 -IncludeDocker。

    终止目标是「本项目进程及其全部后代」，而不是按端口杀进程。这一点很关键：
    uvicorn --reload 会用 multiprocessing 派生实际服务的子进程，该子进程的命令行
    形如 `python.exe -c "from multiprocessing.spawn import spawn_main; ... parent_pid=NNN"`，
    **不含任何项目标识**；而且监听 socket 由父进程创建、被子进程继承，Windows 会把
    持有者记成**已死的父 PID**，直接查端口持有者会指向一个不存在的进程。因此这里做四件事：

      1. 匹配命令行引用本项目的进程（父进程）；
      2. 递归纳入它们的全部后代（父子关系链）；
      3. 认领声明父进程仍在匹配集中的 multiprocessing 子进程；
      4. 认领**声明父进程已消失**的 multiprocessing 工作进程（即上一轮遗留的孤儿）。

    结束后会复核端口是否真正释放，并如实报告（不谎报成功）。

.PARAMETER IncludeDocker
    同时停止 postgres-prod / redis-prod 容器。

.PARAMETER BackendPort
    后端端口，默认 8000（用于结束后的释放复核）。

.PARAMETER FrontendPort
    前端端口，默认 5173。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\stop-all.ps1

.EXAMPLE
    .\scripts\stop-all.ps1 -IncludeDocker
#>
[CmdletBinding()]
param(
    [switch]$IncludeDocker,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'

$PG_CONTAINER = 'postgres-prod'
$REDIS_CONTAINER = 'redis-prod'

function Write-Step { param([string]$Text) Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "    [OK] $Text" -ForegroundColor Green }
function Write-Info { param([string]$Text) Write-Host "    [-]  $Text" -ForegroundColor DarkGray }
function Write-Warn2{ param([string]$Text) Write-Host "    [!]  $Text" -ForegroundColor Yellow }

# 只在"命令行引用了本项目"时才纳入父进程：避免误杀同机的其他 Python/Node 进程。
# 子进程不靠 pattern 命中，而是靠下面的父子关系与 parent_pid 认领。
$patterns = @(
    'finance_agent\.main:app',      # 后端 uvicorn
    'finance_agent\.celery_app',    # Celery worker
    'FinanceAgent[/\\]frontend'     # 前端 vite（工作目录在项目内）
)

function Get-ProjectProcessSet {
    <# 返回应当终止的进程数组：命中的父进程 + 其后代 + multiprocessing 孤儿。 #>
    $all = @(Get-CimInstance Win32_Process)
    $ids = [System.Collections.Generic.HashSet[int]]::new()

    foreach ($proc in $all) {
        $cl = $proc.CommandLine
        if (-not $cl) { continue }
        foreach ($pattern in $patterns) {
            if ($cl -match $pattern) {
                [void]$ids.Add([int]$proc.ProcessId)
                break
            }
        }
    }

    # 展开后代：父进程被命中时，其子/孙进程（含 --reload 的派生进程）一并纳入。
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($proc in $all) {
            if ($ids.Contains([int]$proc.ParentProcessId) -and
                -not $ids.Contains([int]$proc.ProcessId)) {
                [void]$ids.Add([int]$proc.ProcessId)
                $changed = $true
            }
        }
    }

    # 认领 multiprocessing 工作进程（uvicorn --reload 实际服务的那个进程）：
    # 命令行里有 parent_pid=<父PID>，但父进程可能已被杀，父子链会断掉。
    #
    # 关键约束：绝不用"父进程不存在"作为认领依据 —— 那会把**任何**项目的
    # multiprocessing 孤儿都杀掉。这里要求它确实在监听本项目的端口，
    # 才认定属于本项目（端口是本项目唯一的可靠归属证据）。
    $ownedPorts = @($BackendPort, $FrontendPort)
    $orphanOwners = @()
    foreach ($port in $ownedPorts) {
        $orphanOwners += @(
            Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess
        )
    }

    foreach ($proc in $all) {
        $cl = $proc.CommandLine
        if (-not $cl -or $cl -notmatch 'parent_pid=(\d+)') { continue }
        $declaredParent = [int]$Matches[1]
        $isMultiprocessingWorker = $cl -match 'multiprocessing' -or $cl -match 'spawn_main'
        if (-not $isMultiprocessingWorker) { continue }

        if ($ids.Contains($declaredParent)) {
            # 父进程仍在本轮匹配集内：正常认领。
            [void]$ids.Add([int]$proc.ProcessId)
        } elseif ($orphanOwners -contains [int]$proc.ProcessId) {
            # 父进程已消失，但它正监听本项目的端口 —— 这是上一轮遗留的孤儿。
            [void]$ids.Add([int]$proc.ProcessId)
        }
    }

    return @($all | Where-Object { $ids.Contains([int]$_.ProcessId) })
}

Write-Step '停止应用进程（后端 / Celery / 前端及其后代）'

$targets = @(Get-ProjectProcessSet)
if ($targets.Count -eq 0) {
    Write-Info '未发现本项目的应用进程（可能已经停止）'
} else {
    # 先杀子后杀父：父进程（如 uvicorn 的 reloader）若先退出，子进程更难定位。
    $ordered = @($targets | Sort-Object ProcessId -Descending)
    $killed = 0
    foreach ($proc in $ordered) {
        $label = "$($proc.Name) (PID $($proc.ProcessId))"
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Ok "已停止 $label"
            $killed++
        } catch {
            # 父子进程一起退出时，后到的那个会报"找不到进程"，属正常竞态。
            Write-Info "$label 已不存在（随其父进程一并退出）"
        }
    }
    Write-Host "    共终止 $killed 个进程" -ForegroundColor Gray
}

# 复核端口是否真正释放：残留孤儿会占着端口，必须如实报告而不是宣称已停止。
Start-Sleep -Seconds 2
foreach ($port in @($BackendPort, $FrontendPort)) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $owners = @($conn.OwningProcess | Sort-Object -Unique) -join ', '
        Write-Warn2 "端口 $port 仍在监听（PID $owners），可能仍有残留进程"
    } else {
        Write-Ok "端口 $port 已释放"
    }
}

if ($IncludeDocker) {
    Write-Step '停止数据库与 Redis 容器'
    foreach ($container in @($PG_CONTAINER, $REDIS_CONTAINER)) {
        docker stop $container *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "容器 $container 已停止"
        } else {
            Write-Info "容器 $container 停止失败或不存在"
        }
    }
} else {
    Write-Host "`n==> 已保留 PostgreSQL / Redis 容器（需一并停止请加 -IncludeDocker）" -ForegroundColor DarkGray
}

Write-Host "`n已停止。" -ForegroundColor Green
Write-Host ''
