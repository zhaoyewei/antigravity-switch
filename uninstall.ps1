# antigravity-switch (agys) Windows 卸载脚本
#   irm https://raw.githubusercontent.com/zhaoyewei/antigravity-switch/main/uninstall.ps1 | iex
# 只删除安装目录（含二进制与源码 shim）；帐号数据 ~/.agy-accounts 保留。
$ErrorActionPreference = 'Stop'

$Dest = if ($env:AGYS_INSTALL_DIR) { $env:AGYS_INSTALL_DIR }
        else { Join-Path $env:USERPROFILE '.agys' }
$Bin = Join-Path $Dest 'bin'

Write-Host "==> 卸载 $Dest（帐号数据 ~/.agy-accounts 保留）"

# 安全护栏：只删「看起来确实是 agys 安装目录」的目录，避免误删自定义路径
$marker = Join-Path $Dest 'install-mode'
$hasBinary = Test-Path (Join-Path $Bin 'agys.exe')
$hasShim = Test-Path (Join-Path $Bin 'agys')
if (-not (Test-Path $Dest)) {
    Write-Host '==> 安装目录不存在，无需卸载'
} elseif (-not ((Test-Path $marker) -or $hasBinary -or $hasShim)) {
    Write-Host "!! $Dest 里没有 agys 安装标记，为防误删已跳过。请确认 AGYS_INSTALL_DIR 是否正确。"
} else {
    Remove-Item -Recurse -Force $Dest
    Write-Host "==> 已删除 $Dest"
}

if ($env:AGYS_SKIP_PATH -ne '1') {
    $userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
    if ($userPath) {
        $parts = $userPath -split ';' | Where-Object { $_ -and $_ -ne $Bin }
        [Environment]::SetEnvironmentVariable('PATH', ($parts -join ';'), 'User')
        Write-Host '==> 已从用户 PATH 移除安装目录（重开终端后生效）'
    }
}

Write-Host '卸载完成。如需删除帐号数据，请手动删除 ~/.agy-accounts（内含凭据）。'
