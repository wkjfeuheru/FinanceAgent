@echo off
REM 双击入口：以绕过执行策略的方式调用 run-evals.ps1
REM 参数会原样透传，例如：run-evals.bat -SkipBaseline

setlocal
set "SCRIPT=%~dp0run-evals.ps1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*

REM 出错时暂停，方便双击运行时看到错误信息
if errorlevel 1 (
    echo.
    echo [评测失败] 请查看上面的错误信息。
    pause
)
endlocal
