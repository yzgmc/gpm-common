#!/bin/bash
###############################################################################
# GPM 一键清理 + 重新部署脚本（Linux 云服务器）
#
# 部署目标：
#   - gpm-web-admin  (后台，接收上报)   端口 8080
#   - gpm-web-server (网页服务端，上报)  端口 8001
#
# 用法：在云服务器上以 root 执行
#   bash gpm-deploy.sh
#
# 可在脚本顶部修改配置区，改端口/密码/公网IP 等。
###############################################################################

set -euo pipefail

# ====================== 配置区（按需修改）======================
DEPLOY_DIR=/opt/gpm
VENV_DIR=$DEPLOY_DIR/venv
GITHUB_USER=yzgmc
# token 从环境变量读，不硬编码（避免泄露）
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
REPOS=(gpm-common gpm-web-admin gpm-web-server)

# 服务端口
ADMIN_PORT=8080   # gpm-web-admin
SERVER_PORT=8001  # gpm-web-server

# 公网地址（用于上报给后台，让后台能反链到本服务端）
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me || echo "127.0.0.1")
PUBLIC_BASE_URL="http://${PUBLIC_IP}:${SERVER_PORT}"

# 初始管理员（默认 admin/admin123，可在此覆盖）
INIT_USER="${GPM_INIT_USER:-admin}"
INIT_PASS="${GPM_INIT_PASS:-admin123}"
# ===============================================================

log() { echo -e "\033[36m[$(date +%H:%M:%S)]\033[0m $*"; }
err() { echo -e "\033[31m[错误]\033[0m $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || err "请用 root 执行：sudo bash gpm-deploy.sh"
[[ -n "$GITHUB_TOKEN" ]] || err "请先设置 GitHub token：export GITHUB_TOKEN=ghp_xxxx"

log "==> 1/8 停止并清理旧服务"
for svc in gpm-web-admin gpm-web-server gpm-server; do
    systemctl stop "$svc" 2>/dev/null && log "  已停止 $svc" || true
    systemctl disable "$svc" 2>/dev/null || true
    rm -f "/etc/systemd/system/${svc}.service"
done
systemctl daemon-reload
log "  旧 systemd 服务已清理"

log "==> 2/8 清理旧部署目录"
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

log "==> 3/8 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl >/dev/null

log "==> 4/8 克隆最新代码"
cd "$DEPLOY_DIR"
for repo in "${REPOS[@]}"; do
    log "  克隆 $repo ..."
    git clone -q "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${repo}.git"
done

log "==> 5/8 创建虚拟环境 + 安装 Python 依赖"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip
pip install -q ./gpm-common
pip install -q -r gpm-web-admin/requirements.txt
pip install -q -r gpm-web-server/requirements.txt
deactivate

log "==> 6/8 生成固定认证密钥（重启后 token 仍有效）"
SECRET_FILE="$DEPLOY_DIR/.auth_secret"
if [[ ! -f "$SECRET_FILE" ]]; then
    python3 -c "import secrets; print(secrets.token_hex(32))" > "$SECRET_FILE"
fi
AUTH_SECRET=$(cat "$SECRET_FILE")
# 写入环境变量文件，供 systemd 引用
cat > "$DEPLOY_DIR/env" <<EOF
GPM_AUTH_SECRET=${AUTH_SECRET}
GPM_HOST=0.0.0.0
EOF
log "  密钥已保存到 $SECRET_FILE"

log "==> 7/8 创建 systemd 服务"

# ---------- gpm-web-admin (8080) ----------
cat > /etc/systemd/system/gpm-web-admin.service <<EOF
[Unit]
Description=GPM Web Admin (后台，接收上报)
After=network.target

[Service]
Type=simple
WorkingDirectory=$DEPLOY_DIR/gpm-web-admin
EnvironmentFile=$DEPLOY_DIR/env
Environment=GPM_PORT=$ADMIN_PORT
ExecStart=$VENV_DIR/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $ADMIN_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ---------- gpm-web-server (8001) ----------
# 注意：不设 GPM_ADMIN_URL 环境变量，避免覆盖 UI 里的修改；
# 启动后通过 API 写入 server.json 持久化，用户后续可在 UI 里热改。
cat > /etc/systemd/system/gpm-web-server.service <<EOF
[Unit]
Description=GPM Web Server (网页服务端，上报到后台)
After=network.target gpm-web-admin.service

[Service]
Type=simple
WorkingDirectory=$DEPLOY_DIR/gpm-web-server
EnvironmentFile=$DEPLOY_DIR/env
Environment=GPM_PORT=$SERVER_PORT
Environment=GPM_PUBLIC_BASE_URL=$PUBLIC_BASE_URL
ExecStart=$VENV_DIR/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $SERVER_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable gpm-web-admin gpm-web-server >/dev/null

log "==> 8/8 启动服务并配置上报地址"
systemctl start gpm-web-admin
sleep 2
systemctl start gpm-web-server
sleep 2

# 通过 API 设置 gpm-web-server 的 admin_url（持久化到 server.json，可热改）
log "  配置 gpm-web-server 上报地址 -> http://127.0.0.1:$ADMIN_PORT"
TOKEN=$(curl -s -X POST "http://127.0.0.1:$SERVER_PORT/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$INIT_USER\",\"password\":\"$INIT_PASS\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || echo "")

if [[ -n "$TOKEN" ]]; then
    curl -s -X PUT "http://127.0.0.1:$SERVER_PORT/api/v1/config" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"admin_url\":\"http://127.0.0.1:$ADMIN_PORT\",\"public_base_url\":\"$PUBLIC_BASE_URL\"}" \
        > /dev/null && log "  上报地址已配置并持久化" || log "  [警告] 配置 API 调用失败，可稍后在 UI 里手动设置"
else
    log "  [警告] 登录失败，跳过自动配置。请稍后在 UI「配置」Tab 手动设置后台地址"
fi

# 等待一次上报到达
log "  等待首次上报..."
sleep 12

# ====================== 验证 ======================
log ""
log "================ 部署结果 ================"
log "公网 IP:        $PUBLIC_IP"
log "gpm-web-admin:  http://$PUBLIC_IP:$ADMIN_PORT  (后台)"
log "gpm-web-server: http://$PUBLIC_IP:$SERVER_PORT  (网页服务端)"
log "默认账号:       $INIT_USER / $INIT_PASS"
log ""

log "服务状态:"
systemctl --no-pager --lines=0 status gpm-web-admin gpm-web-server 2>/dev/null | grep -E "Active:|●" || true
log ""

log "后台是否收到 gpm-web-server 上报:"
ADMIN_TOKEN=$(curl -s -X POST "http://127.0.0.1:$ADMIN_PORT/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$INIT_USER\",\"password\":\"$INIT_PASS\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || echo "")
if [[ -n "$ADMIN_TOKEN" ]]; then
    REPORTERS=$(curl -s "http://127.0.0.1:$ADMIN_PORT/api/v1/dashboard" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"在线 {d['reporters_online']}/{d['reporters_total']}\")" 2>/dev/null || echo "查询失败")
    log "  $REPORTERS"
else
    log "  [警告] 后台登录失败，无法验证"
fi
log ""

log "常用命令:"
log "  查看日志:   journalctl -u gpm-web-admin -f"
log "             journalctl -u gpm-web-server -f"
log "  重启服务:   systemctl restart gpm-web-admin"
log "             systemctl restart gpm-web-server"
log "  修改配置:   浏览器打开 http://$PUBLIC_IP:$SERVER_PORT -> 配置 Tab"
log "=========================================="
