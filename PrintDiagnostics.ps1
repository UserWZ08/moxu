param(
    [switch]$NoPause,
    [ValidateRange(1,60)][int]$QueryTimeoutSeconds = 12
)
$ErrorActionPreference = 'Stop'
$reportPath = $null
$script:failedQueries = 0
$reportName = '打印诊断-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.txt'

try {
    # Create the report before any driver or service query. Try another writable
    # location when the installation directory is protected.
    $locations = @(
        $PSScriptRoot,
        [Environment]::GetFolderPath('Desktop'),
        [Environment]::GetFolderPath('MyDocuments'),
        $env:TEMP
    ) | Where-Object { $_ } | Select-Object -Unique
    $writeFailures = [System.Collections.Generic.List[string]]::new()
    foreach ($location in $locations) {
        try {
            if (-not (Test-Path -LiteralPath $location -PathType Container)) { continue }
            $candidate = Join-Path $location $reportName
            @(
                '墨序 · 只读打印诊断',
                ('开始时间：' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
                ('PowerShell：' + $PSVersionTable.PSVersion.ToString()),
                '不修改驱动或注册表、不重启打印服务、不清除打印任务。',
                '以下查询逐项执行；如超时，仅结束本工具创建的查询子进程。'
            ) | Set-Content -LiteralPath $candidate -Encoding UTF8
            $reportPath = $candidate
            break
        } catch { $writeFailures.Add($location + '：' + $_.Exception.Message) }
    }
    if (-not $reportPath) { throw ('无法创建报告。' + [Environment]::NewLine + ($writeFailures -join [Environment]::NewLine)) }
    Write-Host ('报告已创建：' + $reportPath)
    if ($writeFailures.Count) {
        Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value ('保存目录已自动切换：' + ($writeFailures -join '；'))
    }

    function Add-DiagnosticSection {
        param([string]$Title, [scriptblock]$ReadAction)
        Write-Host ('正在查询：' + $Title)
        Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value @('',('【' + $Title + '】'),('查询开始：' + (Get-Date -Format 'HH:mm:ss')))
        $queryProcess = $null
        try {
            # Separate read-only processes bound each query's duration, even if
            # the spooler or a driver does not respond. No system process is killed.
            $query = "`$ErrorActionPreference='Stop'; `$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(`$false); try { & { " + $ReadAction.ToString() + " } | Out-String -Width 240 | Write-Output } catch { Write-Output ('无法读取：' + `$_.Exception.Message); exit 2 }"
            $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($query))
            $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
            $startInfo.FileName = Join-Path $PSHOME 'powershell.exe'
            if (-not (Test-Path -LiteralPath $startInfo.FileName)) { $startInfo.FileName = Join-Path $PSHOME 'pwsh.exe' }
            $startInfo.Arguments = '-NoProfile -NonInteractive -EncodedCommand ' + $encoded
            $startInfo.UseShellExecute = $false
            $startInfo.CreateNoWindow = $true
            $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
            $startInfo.RedirectStandardOutput = $true
            $startInfo.RedirectStandardError = $true
            $startInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
            $startInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
            $queryProcess = [System.Diagnostics.Process]::Start($startInfo)
            $stdout = $queryProcess.StandardOutput.ReadToEndAsync()
            $stderr = $queryProcess.StandardError.ReadToEndAsync()
            if (-not $queryProcess.WaitForExit($QueryTimeoutSeconds * 1000)) {
                $script:failedQueries++
                $queryProcess.Kill()
                $queryProcess.WaitForExit()
                Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value ('查询超过 ' + $QueryTimeoutSeconds + ' 秒，已停止本次查询；未停止系统打印服务。')
            } else {
                $outputText = $stdout.GetAwaiter().GetResult()
                $errorText = $stderr.GetAwaiter().GetResult()
                if ($queryProcess.ExitCode -ne 0) { $script:failedQueries++ }
                if ($outputText.Trim()) { Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value $outputText.Trim() }
                elseif ($queryProcess.ExitCode -eq 0) { Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value '没有匹配记录。' }
                if ($errorText.Trim()) { Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value ('查询错误输出：' + $errorText.Trim()) }
                Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value ('查询退出码：' + $queryProcess.ExitCode)
            }
        } catch {
            $script:failedQueries++
            Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value ('查询失败：' + $_.Exception.Message)
        } finally {
            if ($null -ne $queryProcess) { $queryProcess.Dispose() }
        }
    }

    Add-DiagnosticSection '打印服务' {
        Get-Service -Name Spooler | Format-List Name,Status,StartType
    }
    Add-DiagnosticSection '打印机与驱动名称' {
        Get-Printer | Sort-Object Name | Format-Table Name,DriverName,PrinterStatus,JobCount,Type -AutoSize
    }
    Add-DiagnosticSection '驱动版本' {
        Get-PrinterDriver | Format-Table Name,Manufacturer,MajorVersion,DriverVersion -AutoSize
    }
    Add-DiagnosticSection '相关运行进程' {
        Get-Process -Name NeighbourPrint,MoXu,spoolsv,splwow64,PrintIsolationHost -ErrorAction SilentlyContinue |
            Format-Table Id,ProcessName,Responding,StartTime -AutoSize
    }
    Add-DiagnosticSection '最近两天打印服务错误' {
        Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-PrintService/Admin';StartTime=(Get-Date).AddDays(-2)} -MaxEvents 30 |
            Format-List TimeCreated,Id,LevelDisplayName,Message
    }
    Add-DiagnosticSection '最近两天相关程序崩溃' {
        Get-WinEvent -FilterHashtable @{LogName='Application';Id=1000,1001,1002;StartTime=(Get-Date).AddDays(-2)} -MaxEvents 100 |
            Where-Object {$_.Message -match '(?i)printui|spoolsv|splwow64|PrintIsolationHost|epson|MoXu|NeighbourPrint'} |
            Select-Object -First 15 | Format-List TimeCreated,Id,Message
    }
    Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value @('',('诊断完成：' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),('未能完整读取的项目数：' + $script:failedQueries),'“访问被拒绝”“未找到服务”等信息可能来自执行环境限制，不能单凭本报告判定驱动或系统服务已经损坏。','日志只保存在本机；本工具没有执行打印系统修复。')
    Write-Host ('诊断完成：' + $reportPath)
    if (-not $NoPause) { Read-Host '按回车退出' | Out-Null }
    exit 0
} catch {
    $failure = '诊断未完成：' + $_.Exception.Message
    if ($reportPath) {
        try { Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value $failure } catch { }
        Write-Host ('已有报告：' + $reportPath)
    }
    [Console]::Error.WriteLine($failure)
    if (-not $NoPause) { Read-Host '按回车退出' | Out-Null }
    exit 1
}
