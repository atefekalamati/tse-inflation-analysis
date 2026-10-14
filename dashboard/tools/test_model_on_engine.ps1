# End-to-end check of the semantic model's DAX on Power BI Desktop's own engine.
#  1. starts msmdsrv.exe (from Power BI Desktop) in a temp folder, bound to this process
#  2. writes a test copy of the model where each table is a DAX DATATABLE built from the CSVs
#     (a standalone engine cannot run Power Query; the measures, relationships, sort orders and
#     formats are the real ones from dashboard/tse_inflation.SemanticModel)
#  3. deploys it, runs dashboard/tools/model_checks.dax, writes the results to -OutFile
#  4. stops the engine
# Usage: powershell -File dashboard/tools/test_model_on_engine.ps1 -OutFile results.tsv
param([Parameter(Mandatory = $true)][string]$OutFile,
      [string]$Python = "venv\Scripts\python.exe",
      [string]$Bin = "C:\Program Files\Microsoft Power BI Desktop\bin")

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root
$work = Join-Path $env:TEMP ("tse_model_engine_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force "$work\Data", "$work\Temp", "$work\Log", "$work\Backup" | Out-Null
$ini = @"
<ConfigurationSettings>
  <DataDir>$work\Data</DataDir>
  <TempDir>$work\Temp</TempDir>
  <LogDir>$work\Log</LogDir>
  <BackupDir>$work\Backup</BackupDir>
  <AllowedBrowsingFolders>$work</AllowedBrowsingFolders>
  <DeploymentMode>2</DeploymentMode>
  <RecoveryModelDefault>1</RecoveryModelDefault>
  <DisklessModeRequested>0</DisklessModeRequested>
  <CleanDataFolderOnStartup>1</CleanDataFolderOnStartup>
  <AutoSetDefaultInitialCatalog>1</AutoSetDefaultInitialCatalog>
  <Port>0</Port>
  <PrivateProcess>$PID</PrivateProcess>
  <InstanceVisible>0</InstanceVisible>
  <Language>1033</Language>
  <Security><RequireClientAuthentication>0</RequireClientAuthentication></Security>
  <Network><ListenOnlyOnLocalConnections>1</ListenOnlyOnLocalConnections></Network>
  <Log><FlightRecorder><Enabled>0</Enabled></FlightRecorder></Log>
</ConfigurationSettings>
"@
[IO.File]::WriteAllText("$work\msmdsrv.ini", $ini, (New-Object System.Text.UTF8Encoding($false)))

$engine = Start-Process -FilePath (Join-Path $Bin "msmdsrv.exe") -ArgumentList @("-c", "-n", "tsecheck", "-s", "`"$work`"") -PassThru -WindowStyle Hidden
try {
    $port = $null
    for ($i = 0; $i -lt 60 -and -not $port; $i++) {
        Start-Sleep -Milliseconds 500
        if ($engine.HasExited) { throw "engine exited during start-up" }
        $port = (Get-NetTCPConnection -OwningProcess $engine.Id -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).LocalPort
    }
    if (-not $port) { throw "engine did not start listening" }
    & $Python src\build_dashboard.py --test-model "$work\model" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "test model generation failed" }
    $log = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_model.ps1") `
        -Port $port -Folder "$work\model\definition" -QueryFile (Join-Path $PSScriptRoot "model_checks.dax") `
        -OutFile $OutFile -Bin $Bin
    Write-Output $log
    if (($log -join "`n") -match "FAILED") { exit 1 }
} finally {
    if (-not $engine.HasExited) { Stop-Process -Id $engine.Id -Force }
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
exit 0
