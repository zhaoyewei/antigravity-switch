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

# 摘掉安装器写进 shell 启动文件的 PATH 标记块（Git Bash / WSL 用户也覆盖到）
$BlockBegin = '# >>> agys installer >>>'
$BlockEnd = '# <<< agys installer <<<'
foreach ($name in @('.bashrc', '.bash_profile', '.bash_login', '.profile', '.zshrc')) {
    $rc = Join-Path $env:USERPROFILE $name
    if (-not (Test-Path $rc)) { continue }
    $text = [System.IO.File]::ReadAllLines($rc)
    if (-not ($text -contains $BlockBegin)) { continue }
    $keep = New-Object System.Collections.Generic.List[string]
    $skip = $false
    foreach ($line in $text) {
        if ($line.Trim() -eq $BlockBegin) { $skip = $true; continue }
        if ($line.Trim() -eq $BlockEnd) { $skip = $false; continue }
        if (-not $skip) { $keep.Add($line) }
    }
    # 用 .NET 写入：PS 5.1 的 Set-Content -Encoding UTF8 会加 BOM，BOM 会让 bash 报第一行错
    [System.IO.File]::WriteAllLines($rc, $keep, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "==> 已清理 $name 中的 agys PATH 配置"
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
