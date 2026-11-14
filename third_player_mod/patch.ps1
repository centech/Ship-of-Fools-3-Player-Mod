param(
    [ValidateSet('Install','Check','Uninstall')]
    [string]$Action = 'Check',
    [string]$GameFolder = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

function Get-BytesHash([byte[]]$Bytes) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
}

try {
    $planPath = Join-Path $PSScriptRoot 'release-plan.json'
    $planBytes = [IO.File]::ReadAllBytes($planPath)
    if ((Get-BytesHash $planBytes) -ne '696fb88570d1eb737c6d544d20461b63467e77b3ccdf4d1b72695d94a9bcbb72') {
        throw 'The download is incomplete or damaged. Please download and extract the mod again.'
    }
    $plan = [Text.Encoding]::UTF8.GetString($planBytes) | ConvertFrom-Json
    $GameFolder = [IO.Path]::GetFullPath($GameFolder)
    $dll = Join-Path $GameFolder 'GameAssembly.dll'
    if (!(Test-Path -LiteralPath $dll -PathType Leaf)) {
        throw 'Game not found. Extract the mod into your Ship of Fools game folder, then try again.'
    }
    $source = [IO.File]::ReadAllBytes($dll)
    $currentHash = Get-BytesHash $source
    $recognized = @($plan.accepted_sha256.PSObject.Properties.Name)
    if ($currentHash -notin $recognized) {
        throw 'This game version is not supported. Nothing was changed. Check the project page for an update.'
    }
    if ($Action -eq 'Check') {
        Write-Host $plan.accepted_sha256.PSObject.Properties[$currentHash].Value
        Write-Host "SHA256: $currentHash"
        exit 0
    }
    # Temporary installer-test copies do not contain the game executable.
    if ((Test-Path -LiteralPath (Join-Path $GameFolder 'ShipOfFools.exe')) -and
        (Get-Process -Name ShipOfFools -ErrorAction SilentlyContinue)) {
        throw 'Please close Ship of Fools, then try again.'
    }
    $operation = $plan.actions.PSObject.Properties[$Action].Value
    if ($currentHash -eq $operation.sha256) {
        if ($Action -eq 'Install') { Write-Host 'The 3 Player Mod is already installed.' }
        else { Write-Host 'The 3 Player Mod is already removed.' }
        exit 0
    }
    $output = New-Object byte[] ([int]$operation.size)
    foreach ($copy in $operation.copies) {
        [Array]::Copy($source,[int]$copy.source,$output,[int]$copy.offset,[int]$copy.length)
    }
    foreach ($write in $operation.writes) {
        $part = [Convert]::FromBase64String($write.data)
        [Array]::Copy($part,0,$output,[int]$write.offset,$part.Length)
    }
    if ((Get-BytesHash $output) -ne $operation.sha256) {
        throw 'The mod could not be prepared. Nothing was changed. Please extract a fresh download.'
    }
    $backup = "$dll.backup-before-3-player-mod"
    if (Test-Path -LiteralPath $backup) {
        if ((Get-BytesHash ([IO.File]::ReadAllBytes($backup))) -notin $recognized) {
            throw 'An existing backup was not recognized. Nothing was changed. See the troubleshooting guide.'
        }
    } else {
        $backupStream = [IO.File]::Open($backup,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try { $backupStream.Write($source,0,$source.Length); $backupStream.Flush($true) }
        finally { $backupStream.Dispose() }
        if ((Get-BytesHash ([IO.File]::ReadAllBytes($backup))) -ne $currentHash) {
            throw 'The backup could not be checked. Your game was not changed.'
        }
    }
    $staged = Join-Path $GameFolder ('.sof-patch-'+[Guid]::NewGuid().ToString('N')+'.tmp')
    try {
        [IO.File]::WriteAllBytes($staged,$output)
        if ((Get-BytesHash ([IO.File]::ReadAllBytes($staged))) -ne $operation.sha256) {
            throw 'The mod could not be checked. Your game was not changed.'
        }
        if ((Get-BytesHash ([IO.File]::ReadAllBytes($dll))) -ne $currentHash) {
            throw 'The game files changed during setup. Close the game and try again.'
        }
        [IO.File]::Replace($staged,$dll,[NullString]::Value)
    } finally {
        if (Test-Path -LiteralPath $staged) { [IO.File]::Delete($staged) }
    }
    if ((Get-BytesHash ([IO.File]::ReadAllBytes($dll))) -ne $operation.sha256) {
        throw 'The last check failed. Your previous game file is in GameAssembly.dll.backup-before-3-player-mod.'
    }
    if ($Action -eq 'Install') {
        Write-Host '3 Player Mod installed successfully!'
        Write-Host 'Start the game, join two players normally, then press a button on the spare gamepad.'
    } else {
        Write-Host '3 Player Mod removed. Your game is back to normal.'
    }
} catch {
    if ($_.Exception -is [UnauthorizedAccessException] -or $_.Exception.InnerException -is [UnauthorizedAccessException]) {
        Write-Host 'Windows could not write to the game folder. Right-click the script and choose Run as administrator.' -ForegroundColor Red
    } else {
        Write-Host $_.Exception.Message -ForegroundColor Red
    }
    exit 1
}
