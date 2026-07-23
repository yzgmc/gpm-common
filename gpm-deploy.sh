#!/bin/bash
###############################################################################
# GPM 一键清理 + 重新部署脚本（Linux 云服务器）—— 融合体单服务版
#
# 部署目标：
#   - gpm-web-admin (融合体：后台 + 服务端合一)  端口 8001
#
# 融合体启动后自动把 admin_url 指向自己，仪表盘自动纳入本服务，无需手动配置。
#
# 用法：在云服务器上以 root 执行
#   sudo bash gpm-deploy.sh <github_token>
###############################################################################

set -euo pipefail

# ====================== 配置区（按需修改）======================
DEPLOY_DIR=/opt/gpm
VENV_DIR=$DEPLOY_DIR/venv
GITHUB_USER=yzgmc
# token 从第一个命令行参数读：sudo bash gpm-deploy.sh ghp_xxxx
GITHUB_TOKEN="${1:-}"
REPOS=(gpm-common gpm-web-admin)

# 服务端口（融合体单端口）
FUSION_PORT=8001

# 公网地址（用于上报给自己，让仪表盘能反链）
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me || echo "127.0.0.1")
PUBLIC_BASE_URL="http://${PUBLIC_IP}:${FUSION_PORT}"

# 初始管理员（默认 admin/admin123，可在此覆盖）
INIT_USER="${GPM_INIT_USER:-admin}"
INIT_PASS="${GPM_INIT_PASS:-admin123}"
# ===============================================================

log() { echo -e "\033[36m[$(date +%H:%M:%S)]\033[0m $*"; }
err() { echo -e "\033[31m[错误]\033[0m $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || err "请用 root 执行：sudo bash gpm-deploy.sh <github_token>"
[[ -n "$GITHUB_TOKEN" ]] || err "请传 GitHub token 作为参数：sudo bash gpm-deploy.sh ghp_xxxx"

log "==> 1/7 停止并清理旧服务（含旧的分离版 gpm-web-admin/gpm-web-server/gpm-server）"
for svc in gpm-web-admin gpm-web-server gpm-server gpm-fusion; do
    systemctl stop "$svc" 2>/dev/null && log "  已停止 $svc" || true
    systemctl disable "$svc" 2>/dev/null || true
    rm -f "/etc/systemd/system/${svc}.service"
done
systemctl daemon-reload
log "  旧 systemd 服务已清理"

log "==> 2/7 清理旧部署目录"
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

log "==> 3/7 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl >/dev/null

log "==> 4/7 克隆最新代码（gpm-common + gpm-web-admin 融合体）"
cd "$DEPLOY_DIR"
for repo in "${REPOS[@]}"; do
    log "  克隆 $repo ..."
    git clone -q "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${repo}.git"
done

log "==> 5/7 创建虚拟环境 + 安装 Python 依赖"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip
pip install -q ./gpm-common
pip install -q -r gpm-web-admin/requirements.txt
deactivate

log "==> 6/7 生成固定认证密钥 + 创建 systemd 服务"
SECRET_FILE="$DEPLOY_DIR/.auth_secret"
if [[ ! -f "$SECRET_FILE" ]]; then
    python3 -c "import secrets; print(secrets.token_hex(32))" > "$SECRET_FILE"
fi
AUTH_SECRET=$(cat "$SECRET_FILE")

# 环境变量文件：固定密钥 + 公网地址（admin_url 默认指向自己，无需设 GPM_ADMIN_URL）
cat > "$DEPLOY_DIR/env" <<EOF
GPM_AUTH_SECRET=${AUTH_SECRET}
GPM_HOST=0.0.0.0
GPM_PUBLIC_BASE_URL=${PUBLIC_BASE_URL}
EOF

# ---------- 融合体服务（单端口） ----------
cat > /etc/systemd/system/gpm-web-admin.service <<EOF
[Unit]
Description=GPM Web Admin (融合体：后台 + 服务端)
After=network.target

[Service]
Type=simple
WorkingDirectory=$DEPLOY_DIR/gpm-web-admin
EnvironmentFile=$DEPLOY_DIR/env
Environment=GPM_PORT=$FUSION_PORT
ExecStart=$VENV_DIR/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $FUSION_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable gpm-web-admin >/dev/null

log "==> 7/7 启动融合体服务"
systemctl start gpm-web-admin
sleep 3

# 等待自上报到达（admin_url 默认指向自己，无需 API 配置）
log "  等待自上报到达仪表盘..."
sleep 12

# ====================== 验证 ======================
log ""
log "================ 部署结果 ================"
log "公网 IP:      $PUBLIC_IP"
log "融合体服务:   http://$PUBLIC_IP:$FUSION_PORT"
log "  - 仪表盘:   http://$PUBLIC_IP:$FUSION_PORT/        (后台，看上报端状态)"
log "  - 服务端:   http://$PUBLIC_IP:$FUSION_PORT/admin  (上传/管理整合包模组)"
log "默认账号:     $INIT_USER / $INIT_PASS"
log ""

log "服务状态:"
systemctl --no-pager --lines=0 status gpm-web-admin 2>/dev/null | grep -E "Active:|●" || true
log ""

log "仪表盘是否收到自上报:"
ADMIN_TOKEN=$(curl -s -X POST "http://127.0.0.1:$FUSION_PORT/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$INIT_USER\",\"password\":\"$INIT_PASS\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || echo "")
if [[ -n "$ADMIN_TOKEN" ]]; then
    REPORTERS=$(curl -s "http://127.0.0.1:$FUSION_PORT/api/v1/dashboard" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"在线 {d['reporters_online']}/{d['reporters_total']}\")" 2>/dev/null || echo "查询失败")
    log "  $REPORTERS"
else
    log "  [警告] 登录失败，无法验证（请确认账号密码）"
fi
log ""

log "常用命令:"
log "  查看日志:   journalctl -u gpm-web-admin -f"
log "  重启服务:   systemctl restart gpm-web-admin"
log "  修改配置:   浏览器打开 http://$PUBLIC_IP:$FUSION_PORT/admin -> 配置 Tab"
log "=========================================="
