# Exercise installer actions on temporary copies.
param(
    [Parameter(Mandatory=$true)][string]$OriginalDll,
    [Parameter(Mandatory=$true)][string]$SirenDll
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('sof-release-test-'+[Guid]::NewGuid().ToString('N'))
$script=Join-Path $PSScriptRoot 'patch.ps1'
$plan=Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'release-plan.json') | ConvertFrom-Json
$dll=Join-Path $fixture 'GameAssembly.dll'
[void][IO.Directory]::CreateDirectory($fixture)
function Hash([string]$p) { (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLowerInvariant() }
function Run([string]$action,[int]$expected=0) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Action $action -GameFolder $fixture
    if ($LASTEXITCODE -ne $expected) { throw "Unexpected exit code $LASTEXITCODE for $action" }
}
try {
    # Keep a pre-update backup in place to verify that it survives upgrades.
    $oldBackup = "$dll.backup-before-3-player-mod"
    [IO.File]::WriteAllText($oldBackup,'Simulated 1.5.3 backup')
    $oldHash = Hash $oldBackup
    foreach ($file in @($OriginalDll, $SirenDll)) {
        $starting=Hash $file
        $variant=$plan.variants | Where-Object original_sha256 -eq $starting
        if (!$variant) { throw 'Unrecognized test input.' }
        $backup="$dll$($variant.backup_suffix)"
        Copy-Item -LiteralPath $file -Destination $dll -Force
        Run 'Check'; Run 'Install'
        if ((Hash $dll) -ne $variant.patched_sha256 -or (Hash $backup) -ne $starting) { throw 'Install/backup mismatch.' }
        Run 'Install'; Run 'Check'; Run 'Uninstall'; Run 'Uninstall'
        if ((Hash $dll) -ne $starting -or (Hash $backup) -ne $starting) { throw 'Uninstall/backup mismatch.' }
        if ((Hash $file) -ne $starting -or (Hash $oldBackup) -ne $oldHash) { throw 'An input or old backup changed.' }

        # A foreign backup for the same variant must stop the install.
        [IO.File]::WriteAllText($backup,'Synthetic unrecognized backup.')
        $badHash=Hash $backup
        Run 'Install' 1
        if ((Hash $dll) -ne $starting -or (Hash $backup) -ne $badHash) { throw 'Unknown-backup refusal changed a file.' }
        [IO.File]::Delete($backup)
        $corrupt=[IO.File]::ReadAllBytes($dll);$corrupt[4096]=$corrupt[4096] -bxor 1
        [IO.File]::WriteAllBytes($dll,$corrupt)
        $unknown=Hash $dll
        Run 'Install' 1
        if ((Hash $dll) -ne $unknown -or (Test-Path -LiteralPath $backup)) { throw 'Unknown-input refusal changed a file.' }
        Write-Host "PASS: $($variant.label), repeated actions, old backup preservation, exact uninstall and refusal paths."
    }
} finally { [IO.Directory]::Delete($fixture,$true) }
exit 0
