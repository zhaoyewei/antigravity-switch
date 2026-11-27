# antigravity-switch (agys) Windows 一键安装脚本
#   irm https://raw.githubusercontent.com/zhaoyewei/antigravity-switch/main/install.ps1 | iex
#
# 下载 GitHub Release 中的单文件 agys.exe（内置 Python 运行时），
# 不需要 Python、不需要 Git Bash。安装到 %USERPROFILE%\.agys\bin 并加入用户 PATH。
# 可用环境变量覆盖：AGYS_INSTALL_DIR / AGYS_BIN_URL / AGYS_BIN_SHA256 /
#                   AGYS_SKIP_PATH=1 / AGYS_GITHUB_OWNER / AGYS_BIN_REF
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # 9 MiB 下载时别刷进度条
# Windows PowerShell 5.1 默认可能协商到 TLS 1.0，GitHub 需要 TLS 1.2
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$Owner = if ($env:AGYS_GITHUB_OWNER) { $env:AGYS_GITHUB_OWNER }
         elseif ($env:GITHUB_OWNER) { $env:GITHUB_OWNER } else { 'zhaoyewei' }
$Repo = 'antigravity-switch'
$Dest = if ($env:AGYS_INSTALL_DIR) { $env:AGYS_INSTALL_DIR }
        else { Join-Path $env:USERPROFILE '.agys' }
$Bin = Join-Path $Dest 'bin'
$Mode = 'binary'

$Arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x86_64' }
$Asset = "agys-windows-$Arch.exe"
if ($env:AGYS_BIN_REF -and $env:AGYS_BIN_REF -ne 'latest') {
    $DefaultUrl = "https://github.com/$Owner/$Repo/releases/download/$($env:AGYS_BIN_REF)/$Asset"
} else {
    $DefaultUrl = "https://github.com/$Owner/$Repo/releases/latest/download/$Asset"
}
$Url = if ($env:AGYS_BIN_URL) { $env:AGYS_BIN_URL } else { $DefaultUrl }
$SkipPath = ($env:AGYS_SKIP_PATH -eq '1')

Write-Host "==> 安装 antigravity-switch (agys) 到 $Dest"
Write-Host "==> 下载独立二进制（内置运行时，无需 Python）：$Asset"

$proxyUrl = $env:HTTPS_PROXY
if (-not $proxyUrl) { $proxyUrl = $env:HTTP_PROXY }
$iwr = @{ UseBasicParsing = $true; Uri = $Url }
if ($proxyUrl) { $iwr['Proxy'] = $proxyUrl }

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("agys-install-" + [guid]::NewGuid().ToString('N') + ".exe")
try {
    Invoke-WebRequest @iwr -OutFile $tmp

    if (-not (Test-Path $tmp) -or (Get-Item $tmp).Length -eq 0) {
        throw '下载内容为空，拒绝安装'
    }

    # 校验：优先 AGYS_BIN_SHA256，其次同 URL 的 .sha256 附件
    $expected = $env:AGYS_BIN_SHA256
    if (-not $expected -and -not $env:AGYS_BIN_URL) {
        try {
            $shaArgs = @{ UseBasicParsing = $true; Uri = ($Url + '.sha256') }
            if ($proxyUrl) { $shaArgs['Proxy'] = $proxyUrl }
            $text = (Invoke-WebRequest @shaArgs).Content
            $expected = ($text.Trim() -split '\s+')[0]
        } catch {
            Write-Host '==> 提示：未找到 .sha256 校验文件，跳过校验'
        }
    }
    if ($expected) {
        $actual = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected.ToLowerInvariant()) {
            throw "SHA-256 校验失败：期望 $expected，实际 $actual"
        }
        Write-Host '==> SHA-256 校验通过'
    }

    New-Item -ItemType Directory -Force -Path $Bin | Out-Null
    # 清掉旧版源码安装的 shim，避免 PATH 里优先命中它们
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Bin 'agys'), (Join-Path $Bin 'agys.cmd')
    $target = Join-Path $Bin 'agys.exe'
    Move-Item -Force $tmp $target
    Set-Content -Path (Join-Path $Dest 'install-mode') -Value 'binary' -Encoding ascii

    if (-not $SkipPath) {
        $userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
        if (-not $userPath) { $userPath = '' }
        $parts = $userPath -split ';' | Where-Object { $_ }
        if ($parts -notcontains $Bin) {
            $newPath = (($parts + $Bin) -join ';')
            [Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
            Write-Host "==> 已把 $Bin 加入用户 PATH（cmd / 新窗口生效）"
        } else {
            Write-Host '==> 用户 PATH 已包含安装目录'
        }
        # 当前会话也接上：通过 `irm ... | iex` 运行时设置的是本进程环境变量，
        # 执行完立刻就能用 agys；用 .\install.ps1 运行时只影响子进程，下面会给出提示。
        $env:PATH = "$Bin;$env:PATH"
    } else {
        Write-Host '==> 跳过 PATH 修改（AGYS_SKIP_PATH=1）'
    }

    Write-Host '==> 验证安装'
    & $target version
    if ($LASTEXITCODE -ne 0) { throw "二进制自检失败（退出码 $LASTEXITCODE）" }
    Write-Host ''
    Write-Host "安装完成（$Mode 模式）。运行 agys doctor 自检，或直接 agys add 添加第一个帐号。"
    if (-not $SkipPath -and -not (Get-Command 'agys.exe' -ErrorAction SilentlyContinue)) {
        Write-Host ''
        Write-Host '当前窗口立刻可用（复制这一行执行；只影响当前窗口）：'
        Write-Host "    `$env:PATH = `"$Bin;`$env:PATH`""
        Write-Host '新开一个终端则自动生效，无需再 source 任何文件。'
    }
    Write-Host '升级：agys update    卸载：irm .../uninstall.ps1 | iex'
}
finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $tmp
}
