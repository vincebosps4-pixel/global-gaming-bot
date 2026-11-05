# One-time migration of the published v1.0.6 Windows SYSTEM supervisor.
# The running bot and its versioned files are managed by the supervisor itself.
$ErrorActionPreference = 'Stop'

function Get-CheckedItem([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Onverwachte koppeling in de installatie: $Path"
    }
    return $item
}

function Set-QuarterHour([string]$Launcher) {
    $oldHash = '0e51f3de3ae24d3bd28fcea8b96866ebb7ad14a50e241b2a78d2bbb6b21a75bd'
    $newHash = '193e851848717b49c30b2124efea2c382dd1bca02325c5676ef1ad8f3f5a7f51'
    $before = (Get-FileHash -LiteralPath $Launcher -Algorithm SHA256).Hash
    if ($before -eq $newHash) { return }
    if ($before -ne $oldHash) { throw 'Deze versie van het Windows-startprogramma wordt niet herkend. De installatie is ongewijzigd.' }
    $source = [IO.File]::ReadAllText($Launcher).Replace('check_at=now+1800', 'check_at=now+900')
    $temp = Join-Path ([IO.Path]::GetDirectoryName($Launcher)) ([guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temp, $source, [Text.UTF8Encoding]::new($false))
        if ((Get-FileHash -LiteralPath $temp -Algorithm SHA256).Hash -ne $newHash) {
            throw 'De timerwijziging kwam niet door de bestandscontrole.'
        }
        # File.Replace preserves the installed file's Windows security descriptor.
        [IO.File]::Replace($temp, $Launcher, [System.Management.Automation.Language.NullString]::Value)
    } finally {
        [IO.File]::Delete($temp)
    }
}

function Restart-RunningBot([string]$TaskName, [string]$Data) {
    $flag = Join-Path $Data 'supervisor.stop'
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $TaskName
    if ($task.State -ne 'Running' -or (Test-Path -LiteralPath $flag)) {
        Write-Host 'Kwartiercontrole ingesteld. De timer gaat in zodra de bot weer start.'
        return
    }
    Write-Host 'Kwartiercontrole ingesteld. De bot rondt lopend werk af en start opnieuw...'
    $stopFile = [IO.File]::Open($flag, 'CreateNew', 'Write', 'None')
    $stopFile.Dispose()
    try {
        $deadline = [datetime]::UtcNow.AddMinutes(4)
        do {
            Start-Sleep -Seconds 2
            $task = Get-ScheduledTask -TaskPath '\' -TaskName $TaskName
        } while ($task.State -eq 'Running' -and [datetime]::UtcNow -lt $deadline)
        if ($task.State -eq 'Disabled') {
            Write-Host 'De Windows-taak is uitgeschakeld. De timer geldt vanaf de volgende start.'
            return
        }
    } finally {
        [IO.File]::Delete($flag)
    }
    if ($task.State -ne 'Ready') {
        throw 'De timer is opgeslagen. Herstart de bot met 4-STOP-BOT en daarna 2-START-BOT zodra de lopende taak klaar is.'
    }
    $since = [datetime]::UtcNow
    Start-ScheduledTask -TaskPath '\' -TaskName $TaskName
    $deadline = $since.AddSeconds(90)
    $health = Join-Path $Data 'healthy'
    do {
        Start-Sleep -Seconds 2
        if ((Test-Path -LiteralPath $health) -and [IO.File]::GetLastWriteTimeUtc($health) -ge $since) {
            Write-Host 'Online en verbonden. De updatecontrole staat op elke 15 minuten.' -ForegroundColor Green
            return
        }
    } while ([datetime]::UtcNow -lt $deadline)
    Write-Host 'Kwartiercontrole ingesteld. Controleer de verbinding straks met 3-STATUS.'
}

function Install-QuarterHour {
    $user = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (!$user.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Klik met rechts op KWARTIERCONTROLE.cmd en kies Als administrator uitvoeren.'
    }
    $base = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'Global Gaming Bot'
    $null = Get-CheckedItem $base
    $acl = Get-Acl -LiteralPath $base
    $sidType = [Security.Principal.SecurityIdentifier]
    $trusted = @('S-1-5-18', 'S-1-5-32-544')
    if (!$acl.AreAccessRulesProtected -or $acl.GetOwner($sidType).Value -notin $trusted) {
        throw 'De beveiliging van de Global Gaming-installatiemap wijkt af.'
    }
    foreach ($rule in $acl.GetAccessRules($true, $true, $sidType)) {
        if ($rule.IdentityReference.Value -notin $trusted) { throw 'Onverwachte rechten op de installatiemap.' }
    }
    $lock = [IO.File]::Open((Join-Path $base 'installatie.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    try {
        $pointer = Get-CheckedItem (Join-Path $base 'actief.txt')
        $id = [IO.File]::ReadAllText($pointer.FullName).Trim()
        if ($id -notmatch '^[0-9a-f]{32}$') { throw 'De actieve installatie is ongeldig.' }
        $active = Get-CheckedItem (Join-Path $base $id)
        $root = Get-CheckedItem (Join-Path $active.FullName 'launcher')
        $launcher = Get-CheckedItem (Join-Path $root.FullName 'launcher.py')
        $data = Get-CheckedItem (Join-Path $root.FullName 'data')
        $name = 'Global Gaming Bot - Systeem'
        $task = Get-ScheduledTask -TaskPath '\' -TaskName $name
        $action = @($task.Actions)
        if ($action.Count -ne 1 -or $action[0].Execute -ne (Join-Path $root.FullName 'engine\pythonw.exe') -or
            $action[0].Arguments -ne ('-Es "' + $launcher.FullName + '"') -or $action[0].WorkingDirectory -ne $root.FullName -or
            $task.Principal.UserId -notin @('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18')) {
            throw 'De Windows-taak komt niet overeen met de Global Gaming-systeeminstallatie.'
        }
        Set-QuarterHour $launcher.FullName
        Restart-RunningBot $name $data.FullName
        if (Test-Path -LiteralPath (Join-Path $root.FullName 'config\PAUSE-UPDATES')) {
            Write-Host 'Automatische updates zijn op deze pc gepauzeerd. De timer geldt zodra je updates hervat.'
        }
    } finally {
        $lock.Dispose()
    }
}

try { Install-QuarterHour }
catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
