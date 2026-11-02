# JSON-lines protocol: owned-process notifications, then one result per request.
# Each COM instance must belong to a new Office process, protecting user sessions.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class OfficeWindow {
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
'@

$applications = @{}
try {
    while ($null -ne ($line = [Console]::ReadLine())) {
        $document = $null
        $reply = @{ code = 0; error = '' }
        try {
            $request = ConvertFrom-Json $line
            $kind = $request.kind
            if (-not $applications.ContainsKey($kind)) {
                $program = switch ($kind) {
                    'word' { 'Word.Application' }
                    'excel' { 'Excel.Application' }
                    'ppt' { 'PowerPoint.Application' }
                    default { throw 'Unknown Office engine' }
                }
                $existingIds = @(
                    Get-Process WINWORD, EXCEL, POWERPNT -ErrorAction SilentlyContinue |
                        ForEach-Object { $_.Id }
                )
                try {
                    $application = New-Object -ComObject $program
                } catch {
                    if ($_.Exception.ToString() -match '80040154|800401F3') {
                        $reply.code = 15
                    }
                    throw
                }
                [uint32]$officeProcessId = 0
                [void][OfficeWindow]::GetWindowThreadProcessId(
                    [IntPtr]$application.HWND, [ref]$officeProcessId
                )
                if ($officeProcessId -eq 0 -or $existingIds -contains $officeProcessId) {
                    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
                    $application = $null
                    throw 'Office reused an existing instance; stopped to protect open documents.'
                }
                $applications[$kind] = $application
                $creationTime = (Get-Process -Id $officeProcessId).StartTime.ToUniversalTime().ToFileTimeUtc()
                [Console]::WriteLine((ConvertTo-Json -Compress @{
                    event = 'office_process'; pid = $officeProcessId; created = $creationTime
                }))
                $application.AutomationSecurity = 3
                if ($kind -ne 'ppt') {
                    $application.Visible = $false
                    $application.DisplayAlerts = 0
                }
                if ($kind -eq 'word') { $application.ScreenUpdating = $false }
            }

            $application = $applications[$kind]
            switch ($kind) {
                'word' {
                    $document = $application.Documents.Open($request.source, $false, $true, $false)
                    $document.ExportAsFixedFormat($request.dest, 17)
                }
                'excel' {
                    $document = $application.Workbooks.Open($request.source, 0, $true)
                    $document.ExportAsFixedFormat(0, $request.dest)
                }
                'ppt' {
                    $document = $application.Presentations.Open($request.source, $true, $false, $false)
                    $document.SaveAs($request.dest, 32)
                }
            }
        } catch {
            if ($reply.code -ne 15) { $reply.code = 1 }
            $reply.error = $_.Exception.ToString()
        } finally {
            if ($null -ne $document) {
                try {
                    switch ($kind) {
                        'word' { $document.Close(0) }
                        'excel' { $document.Close($false) }
                        'ppt' { $document.Close() }
                    }
                } catch {
                    $reply.code = 1
                    $reply.error = $_.Exception.ToString()
                } finally {
                    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
                }
            }
        }
        [Console]::WriteLine((ConvertTo-Json -Compress $reply))
    }
} finally {
    foreach ($application in $applications.Values) {
        try { $application.Quit() } catch {} finally {
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
        }
    }
}
