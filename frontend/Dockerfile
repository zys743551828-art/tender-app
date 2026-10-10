# syntax=docker/dockerfile:1.7
# =============================================================================
# 施组工作台 · 前端镜像（React + Vite 静态 SPA，由 nginx-unprivileged 提供服务并反向代理 /api）
#
# 构建上下文：frontend
#   构建阶段：node:22-alpine，npm ci（严格按 package-lock.json）→ npm run build（含 tsc 类型检查）
#   运行阶段：nginxinc/nginx-unprivileged（uid 101，非 root，监听 8080；TLS 模式另听 8443）
#
# 配置在运行期由官方镜像的 /etc/nginx/templates/*.template + envsubst 渲染到 /etc/nginx/conf.d/，
# 所以“OSS 公网端点、限流速率、API 上游”等无需重建镜像。可用的 WEB_* 变量见 nginx/templates/*.template 与 deploy/.env.example。
# =============================================================================

ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.30.5-alpine

# -----------------------------------------------------------------------------
# build：安装依赖并构建 dist/
# -----------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS build
# 国内网络可指定 npm 镜像：--build-arg NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_REGISTRY=""
WORKDIR /src

# 先只复制依赖清单，利用层缓存：源码变化不会重新安装依赖
COPY package.json package-lock.json ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
 && npm ci --no-audit --no-fund

COPY . .
# build 脚本 = tsc --noEmit && vite build；类型错误会使构建失败（期望行为）。PDF.js worker 由 Vite 打包，不依赖 CDN。
RUN npm run build \
 && test -f dist/index.html

# -----------------------------------------------------------------------------
# runtime：nginx（非 root）
# -----------------------------------------------------------------------------
FROM ${NGINX_IMAGE} AS runtime

ARG VERSION=dev
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="bidwb-web" \
      org.opencontainers.image.description="施组工作台前端静态资源与反向代理" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

# 官方 envsubst 脚本只替换以 WEB_ 开头的变量，避免把 nginx 自己的 $host、$uri 等误替换
ENV NGINX_ENVSUBST_FILTER="^WEB_" \
    WEB_API_UPSTREAM="api:8000" \
    WEB_CSP_CONNECT_EXTRA="" \
    WEB_CLIENT_MAX_BODY_SIZE="5m" \
    WEB_LOGIN_RATE="10r/m" \
    WEB_API_RATE="30r/s" \
    WEB_SET_REAL_IP_FROM="10.0.0.0/8" \
    WEB_SERVER_NAME="_" \
    WEB_MODE="http" \
    WEB_PUBLIC_HOST="localhost"

# 配置模板（.template 后缀由官方 envsubst 脚本渲染到 /etc/nginx/conf.d/，子文件名去掉后缀）
COPY --chown=0:0 nginx/templates/ /etc/nginx/templates/
COPY --from=build --chown=0:0 /src/dist/ /usr/share/nginx/html/

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/nginx-health"]
