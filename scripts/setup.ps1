<#
.SYNOPSIS
  Cai dat / cap nhat thu vien Revit MCP dung chung tren mot may Windows.

.DESCRIPTION
  Chay lai bao nhieu lan cung duoc (idempotent):
    1. Clone hoac git pull repo vao C:\RevitMCP\mcp-server-for-revit-python.extension
    2. Cat cac extension MCP trung lap trong %APPDATA%\pyRevit\Extensions sang Extensions_backup
    3. Khai bao C:\RevitMCP la thu muc extension cua pyRevit va bat Routes server
    4. Tro "Revit Connector" trong claude_desktop_config.json vao repo (venv rieng tung may)
    5. Lien ket cac skill trong .agents\skills vao %USERPROFILE%\.claude\skills (Claude Code)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File setup.ps1 -RepoUrl https://github.com/<ban>/revit-mcp.git
#>
param(
    [string]$RepoUrl = "",
    [string]$Root = "C:\RevitMCP",
    [string]$ServerName = "Revit Connector",
    [string]$VenvDir = "C:\RevitMCP-venv"
)

$ErrorActionPreference = "Stop"
$ExtName = "mcp-server-for-revit-python.extension"
$Repo = Join-Path $Root $ExtName

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }

# 1. Repo ---------------------------------------------------------------
Step "Repo: $Repo"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Chua cai Git. Tai tai https://git-scm.com/download/win" }
if (Test-Path (Join-Path $Repo ".git")) {
    git -C $Repo pull --ff-only
} elseif ($RepoUrl) {
    New-Item -ItemType Directory -Force $Root | Out-Null
    git clone $RepoUrl $Repo
} else {
    throw "Chua co repo tai $Repo. Chay lai voi -RepoUrl <link GitHub>."
}

# 2. Extension trung lap -------------------------------------------------
Step "Kiem tra extension MCP trung lap trong pyRevit\Extensions"
$pyrevitDir = Join-Path $env:APPDATA "pyRevit"
$extDir = Join-Path $pyrevitDir "Extensions"
$backupDir = Join-Path $pyrevitDir "Extensions_backup"
foreach ($dup in @("revit-mcp-python.extension", $ExtName)) {
    $p = Join-Path $extDir $dup
    if (Test-Path $p) {
        New-Item -ItemType Directory -Force $backupDir | Out-Null
        $dest = Join-Path $backupDir ($dup + "." + (Get-Date -Format "yyyyMMdd-HHmmss"))
        Move-Item $p $dest
        Write-Host "  Da cat $dup -> $dest (hai extension cung dang ky route revit_mcp se xung dot)"
    }
}

# 3. pyRevit: duong dan extension + Routes ------------------------------
Step "Cau hinh pyRevit"
$ini = Join-Path $pyrevitDir "pyRevit_config.ini"
$pyrevitCli = Get-Command pyrevit -ErrorAction SilentlyContinue
if ($pyrevitCli) {
    pyrevit extensions paths add $Root | Out-Null
    Write-Host "  Da them $Root vao Custom Extension Directories"
} else {
    Write-Warning "Khong tim thay lenh pyrevit. Hay them $Root trong pyRevit > Settings > Custom Extension Directories."
}
if (Test-Path $ini) {
    $text = [IO.File]::ReadAllText($ini)
    $new = [regex]::Replace($text, '(?ms)(^\[routes\]\s*?\r?\n(?:(?!^\[).)*?^enabled\s*=\s*)false', '${1}true')
    if ($new -ne $text) {
        Copy-Item $ini "$ini.bak" -Force
        [IO.File]::WriteAllText($ini, $new)
        Write-Host "  Da bat Routes server (ban sao luu: pyRevit_config.ini.bak)"
    } else {
        Write-Host "  Routes server da bat san (hoac chua co muc [routes] - bat trong pyRevit > Settings > Routes)"
    }
}

# 4. Claude Desktop config ----------------------------------------------
Step "Cau hinh Claude: $ServerName"
$uv = Get-Command uv -ErrorAction SilentlyContinue
$uvPath = if ($uv) { $uv.Source } else {
    $found = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Recurse -Filter uv.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $found.FullName } else { $null }
}
if (-not $uvPath) { throw "Chua cai uv. Chay: winget install astral-sh.uv  (roi chay lai script nay)" }

$cfgPath = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
# Claude Desktop giu config trong bo nho va ghi de file khi dang chay -> phai tat Claude truoc.
if (Get-Process -Name "Claude" -ErrorAction SilentlyContinue) {
    Write-Warning "Claude dang chay va se ghi de thay doi nay. Thoat han Claude (ca icon o khay he thong), roi chay lai script tu PowerShell."
}
if (Test-Path $cfgPath) {
    Copy-Item $cfgPath "$cfgPath.bak" -Force
    $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    New-Item -ItemType Directory -Force (Split-Path $cfgPath) | Out-Null
    $cfg = New-Object PSObject
}
if (-not $cfg.PSObject.Properties["mcpServers"]) {
    $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue (New-Object PSObject)
}
$server = [ordered]@{
    command = $uvPath
    args    = @("run", "--directory", $Repo, "main.py")
    env     = [ordered]@{
        UV_PROJECT_ENVIRONMENT  = $VenvDir   # venv o ngoai repo -> khong dong bo, khong xung dot giua cac may
        PYTHONDONTWRITEBYTECODE = "1"
    }
}
if ($cfg.mcpServers.PSObject.Properties[$ServerName]) { $cfg.mcpServers.PSObject.Properties.Remove($ServerName) }
$cfg.mcpServers | Add-Member -NotePropertyName $ServerName -NotePropertyValue $server
$json = $cfg | ConvertTo-Json -Depth 50
[IO.File]::WriteAllText($cfgPath, $json, (New-Object Text.UTF8Encoding($false)))
Write-Host "  Da ghi $cfgPath (ban sao luu: .bak)"

# 5. Skills cho Claude Code ----------------------------------------------
Step "Lien ket skills vao Claude Code"
$skillsSrc = Join-Path $Repo ".agents\skills"
$skillsDst = Join-Path $env:USERPROFILE ".claude\skills"
New-Item -ItemType Directory -Force $skillsDst | Out-Null
Get-ChildItem $skillsSrc -Directory | Where-Object { Test-Path (Join-Path $_.FullName "SKILL.md") } | ForEach-Object {
    $link = Join-Path $skillsDst $_.Name
    if (Test-Path $link) {
        $item = Get-Item $link -Force
        if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Write-Warning "  Bo qua $($_.Name): $link da ton tai va khong phai lien ket"
            return
        }
        cmd /c rmdir "$link" | Out-Null
    }
    cmd /c mklink /J "$link" "$($_.FullName)" | Out-Null
    Write-Host "  $($_.Name)"
}

Step "Xong. Viec con lai (lam bang tay):"
Write-Host "  1. Revit: tab pyRevit > Reload"
Write-Host "  2. Revit: tab MCP > Bridge > Connect > Yes   (moi may 1 lan)"
Write-Host "  3. Thoat han Claude roi mo lai"
