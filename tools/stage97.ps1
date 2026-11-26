[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Worktree,
    [Parameter(Mandatory)] [string]$Python,
    [Parameter(Mandatory)] [ValidateSet('thesis-e2e-stage97')] [string]$Project,
    [ValidateSet('preflight','build','infra','keys','services','schema','workers','readiness','workflow-probe','normal','fault','collect','postgres','stop')] [string]$Action = 'preflight',
    [string]$EnvFile,
    [string]$Approval,
    [string]$ArtifactDir,
    [string]$Case,
    [string]$Trace,
    [switch]$Resources
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Worktree).Path
$expected = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ($root -ne $expected) { throw 'WRONG_WORKTREE' }
$interpreter = (Resolve-Path -LiteralPath $Python).Path
$params = @('-B', '-m', 'tools.stage97_runtime', $Action, '--worktree', $root, '--project', $Project)
if ($EnvFile) { $params += @('--env-file', $EnvFile) }
if ($Approval) { $params += @('--approval', $Approval) }
if ($ArtifactDir) { $params += @('--artifact-dir', $ArtifactDir) }
if ($Case) { $params += @('--case', $Case) }
if ($Trace) { $params += @('--trace', $Trace) }
if ($Resources) { $params += '--resources' }
Push-Location -LiteralPath $root
try {
    & $interpreter @params
    $result = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $result
