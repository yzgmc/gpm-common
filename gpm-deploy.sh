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
warn() { echo -e "\033[33m[警告]\033[0m $*"; }

[[ $EUID -eq 0 ]] || err "请用 root 执行：sudo bash gpm-deploy.sh <github_token>"
[[ -n "$GITHUB_TOKEN" ]] || err "请传 GitHub token 作为参数：sudo bash gpm-deploy.sh ghp_xxxx"

log "==> 1/8 停止并清理旧服务（含旧的分离版 gpm-web-admin/gpm-web-server/gpm-server）"
for svc in gpm-web-admin gpm-web-server gpm-server gpm-fusion; do
    systemctl stop "$svc" 2>/dev/null && log "  已停止 $svc" || true
    systemctl disable "$svc" 2>/dev/null || true
    rm -f "/etc/systemd/system/${svc}.service"
done
systemctl daemon-reload
log "  旧 systemd 服务已清理"

# 强制杀掉占用 8001 端口的进程（防止旧进程残留导致端口冲突）
log "==> 2/8 清理端口占用（确保 ${FUSION_PORT} 端口可用）"
PORT_PIDS=$(lsof -ti :${FUSION_PORT} 2>/dev/null || true)
if [[ -n "$PORT_PIDS" ]]; then
    log "  端口 ${FUSION_PORT} 被占用 (PID: $PORT_PIDS)，强制清理..."
    echo "$PORT_PIDS" | xargs kill -9 2>/dev/null || true
    sleep 2
    # 再次检查
    REMAIN=$(lsof -ti :${FUSION_PORT} 2>/dev/null || true)
    if [[ -n "$REMAIN" ]]; then
        err "端口 ${FUSION_PORT} 仍被占用 (PID: $REMAIN)，无法启动。请手动清理: kill -9 $REMAIN"
    fi
    log "  端口已释放"
else
    log "  端口 ${FUSION_PORT} 空闲"
fi

# 同时清理 8080 旧后台端口
PORT_8080_PIDS=$(lsof -ti :8080 2>/dev/null || true)
if [[ -n "$PORT_8080_PIDS" ]]; then
    log "  清理旧后台端口 8080 (PID: $PORT_8080_PIDS)..."
    echo "$PORT_8080_PIDS" | xargs kill -9 2>/dev/null || true
fi

log "==> 3/8 清理旧部署目录"
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

log "==> 4/8 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl lsof >/dev/null
log "  系统依赖已安装"

log "==> 5/8 克隆最新代码（gpm-common + gpm-web-admin 融合体）"
cd "$DEPLOY_DIR"
for repo in "${REPOS[@]}"; do
    log "  克隆 $repo ..."
    git clone -q "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${repo}.git" \
        || err "克隆 $repo 失败，请检查 token 和网络"
done
log "  代码克隆完成"

log "==> 6/8 创建虚拟环境 + 安装 Python 依赖"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip
log "  安装 gpm-common..."
pip install ./gpm-common 2>&1 | tail -1
log "  安装 gpm-web-admin 依赖..."
pip install -r gpm-web-admin/requirements.txt 2>&1 | tail -1
deactivate
log "  Python 依赖安装完成"

# 验证关键模块能导入
log "  验证模块导入..."
"$VENV_DIR/bin/python" -c "from app.main import app; print('  导入验证通过')" 2>&1 \
    || err "模块导入失败，请检查依赖是否完整安装。尝试: $VENV_DIR/bin/pip install httpx pydantic fastapi uvicorn"

log "==> 7/8 生成固定认证密钥 + 创建 systemd 服务"
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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable gpm-web-admin >/dev/null

log "==> 8/8 启动融合体服务"
systemctl start gpm-web-admin
sleep 3

# 检查服务是否真的启动了
if ! systemctl is-active --quiet gpm-web-admin; then
    log ""
    log "================ 服务启动失败 ================"
    log "服务状态:"
    systemctl status gpm-web-admin --no-pager -l 2>&1 | head -20
    log ""
    log "最近日志:"
    journalctl -u gpm-web-admin --no-pager -n 30 2>&1
    err "服务启动失败，请检查上方日志"
fi
log "  服务已启动 (active)"

# 等待端口开始监听
log "  等待端口监听..."
for i in $(seq 1 10); do
    if lsof -i :${FUSION_PORT} >/dev/null 2>&1; then
        log "  端口 ${FUSION_PORT} 已监听"
        break
    fi
    sleep 1
done

# 测试 HTTP 是否响应
log "  测试 HTTP 响应..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:${FUSION_PORT}/api/info 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" != "200" ]]; then
    warn "HTTP 响应异常 (HTTP $HTTP_CODE)，服务可能还在启动中，等待 5 秒后重试..."
    sleep 5
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:${FUSION_PORT}/api/info 2>/dev/null || echo "000")
fi

# 等待自上报到达
log "  等待自上报到达仪表盘..."
sleep 12

# ====================== 验证 ======================
log ""
log "================ 部署结果 ================"
log "公网 IP:      $PUBLIC_IP"
log "融合体服务:   http://$PUBLIC_IP:$FUSION_PORT"
log "  - 仪表盘:   http://$PUBLIC_IP:$FUSION_PORT/        (后台，看上报端状态)"
log "  - 服务端:   http://$PUBLIC_IP:$FUSION_PORT/admin  (上传/管理整合包模组)"
log "  - API文档:  http://$PUBLIC_IP:$FUSION_PORT/docs   (Swagger UI)"
log "默认账号:     $INIT_USER / $INIT_PASS"
log ""

if [[ "$HTTP_CODE" == "200" ]]; then
    log "HTTP 响应: 正常 (HTTP 200)"

    # 验证登录
    log "验证登录..."
    LOGIN_RESP=$(curl -s --max-time 5 -X POST "http://127.0.0.1:${FUSION_PORT}/api/v1/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"$INIT_USER\",\"password\":\"$INIT_PASS\"}" 2>/dev/null || echo "")
    ADMIN_TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || echo "")

    if [[ -n "$ADMIN_TOKEN" ]]; then
        log "  登录: 成功"

        # 验证仪表盘
        log "验证仪表盘自上报..."
        DASH_RESP=$(curl -s --max-time 5 "http://127.0.0.1:${FUSION_PORT}/api/v1/dashboard" \
            -H "Authorization: Bearer $ADMIN_TOKEN" 2>/dev/null || echo "")
        REPORTERS=$(echo "$DASH_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"在线 {d['reporters_online']}/{d['reporters_total']}\")" 2>/dev/null || echo "查询失败")
        log "  仪表盘: $REPORTERS"
    else
        warn "登录失败，响应: $LOGIN_RESP"
        warn "可能原因: users.json 数据异常。可删除 data/users.json 重启服务恢复默认 admin/admin123"
    fi
else
    warn "HTTP 响应异常 (HTTP $HTTP_CODE)"
    warn "最近日志:"
    journalctl -u gpm-web-admin --no-pager -n 15 2>&1 | while read -r line; do log "  $line"; done
fi
log ""

log "常用命令:"
log "  查看日志:   journalctl -u gpm-web-admin -f"
log "  重启服务:   systemctl restart gpm-web-admin"
log "  服务状态:   systemctl status gpm-web-admin"
log "  修改配置:   浏览器打开 http://$PUBLIC_IP:$FUSION_PORT/admin -> 配置 Tab"
log "=========================================="
