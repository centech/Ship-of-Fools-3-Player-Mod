# Exercise the real installer on temporary copies; never edit the source game files.
param(
    [Parameter(Mandatory=$true)][string]$OriginalDll,
    [string[]]$PreviousDll = @()
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('sof-release-test-'+[Guid]::NewGuid().ToString('N'))
$script=Join-Path $PSScriptRoot 'patch.ps1'
$plan=Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'release-plan.json') | ConvertFrom-Json
$dll=Join-Path $fixture 'GameAssembly.dll'
$backup="$dll.backup-before-3-player-mod"
New-Item -ItemType Directory -Path $fixture -Force | Out-Null
function Hash([string]$p) { (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLowerInvariant() }
function Run([string]$action,[int]$expected=0) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Action $action -GameFolder $fixture
    if ($LASTEXITCODE -ne $expected) { throw "Unexpected exit code $LASTEXITCODE for $action" }
}
try {
    if ((Hash $OriginalDll) -ne $plan.original_sha256) { throw 'The original input is not the verified original game.' }
    foreach ($file in (@($OriginalDll)+$PreviousDll)) {
        $starting=Hash $file
        if ($starting -notin @($plan.accepted_sha256.PSObject.Properties.Name)) { throw 'Unrecognized test input.' }
        Copy-Item -LiteralPath $file -Destination $dll -Force
        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup }
        Run 'Check';Run 'Install'
        if ((Hash $dll) -ne $plan.patched_sha256 -or (Hash $backup) -ne $starting) { throw 'Install/backup mismatch.' }
        Run 'Install';Run 'Check';Run 'Uninstall';Run 'Uninstall'
        if ((Hash $dll) -ne $plan.original_sha256 -or (Hash $backup) -ne $starting) { throw 'Uninstall/backup mismatch.' }
        if ((Hash $file) -ne $starting) { throw 'Source input changed.' }
    }
    # An unknown backup must stop installation and leave both files untouched.
    [IO.File]::WriteAllText($backup,'Synthetic unrecognized backup.')
    $backupHash=Hash $backup
    Run 'Install' 1
    if ((Hash $dll) -ne $plan.original_sha256 -or (Hash $backup) -ne $backupHash) { throw 'Unknown-backup refusal changed a file.' }
    [IO.File]::Delete($backup)
    $corrupt=[IO.File]::ReadAllBytes($dll);$corrupt[4096]=$corrupt[4096] -bxor 1
    [IO.File]::WriteAllBytes($dll,$corrupt)
    $unknown=Hash $dll
    Run 'Install' 1
    if ((Hash $dll) -ne $unknown -or (Test-Path -LiteralPath $backup)) { throw 'Unknown-input refusal changed a file.' }
    Write-Host 'PASS: clean install, previous-version upgrade, repeat actions, backup preservation, exact uninstall and refusal paths.'
} finally { [IO.Directory]::Delete($fixture,$true) }
exit 0
