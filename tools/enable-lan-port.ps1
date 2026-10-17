# Разрешает входящие подключения к серверу на указанном порту
# при WSL2 mirrored networking. Запускать от администратора (или через UAC).
param([int]$Port = 8002)

$ErrorActionPreference = "Stop"
$ruleName = "Tomato server $Port"

if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $Port -Profile Any | Out-Null
    Write-Host "Windows Firewall: rule '$ruleName' added"
}

$wslVm = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"
$hyperVName = "TomatoServer$Port"
if (Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {
    if (-not (Get-NetFirewallHyperVRule -Name $hyperVName -ErrorAction SilentlyContinue)) {
        New-NetFirewallHyperVRule -Name $hyperVName -DisplayName $ruleName `
            -Direction Inbound -VMCreatorId $wslVm -Protocol TCP -LocalPorts $Port `
            -Action Allow | Out-Null
        Write-Host "Hyper-V Firewall: rule for WSL port $Port added"
    }
} else {
    Set-NetFirewallHyperVVMSetting -Name $wslVm -DefaultInboundAction Allow
    Write-Host "Hyper-V Firewall: default inbound = Allow"
}
