FROM node:22-alpine AS web-build

WORKDIR /app
ARG VITE_BRAND_NAME=Component Warehouse
ARG VITE_BRAND_SHORT=Component Warehouse
ARG VITE_BRAND_PERSONAL_TITLE=Component Warehouse · Personal
ARG VITE_BRAND_TEAM_TITLE=Component Warehouse · Team
ARG VITE_BRAND_SHOW_LOGO=1
ARG VITE_PWA_PERSONAL_NAME=WXY LAB 器件管理
ARG VITE_PWA_TEAM_NAME=WXY LAB 器件管理团队版
ARG VITE_COPYRIGHT_TEXT=© 2026 Component Warehouse contributors
ARG VITE_ICP_RECORD_TEXT=ICP 备案号：冀ICP备2026009111号-1
ARG VITE_ICP_RECORD_URL=https://beian.miit.gov.cn/
ARG VITE_PUBLIC_SECURITY_RECORD_TEXT=冀公网安备13010402003414号
ARG VITE_PUBLIC_SECURITY_RECORD_URL=https://beian.mps.gov.cn/#/query/webSearch
ARG VITE_FEATURE_EDA_ENABLED=1
ARG VITE_AUTH_IDLE_TIMEOUT_MINUTES=720
ARG VITE_AUTH_MAX_SESSION_HOURS=168
ENV VITE_BRAND_NAME=$VITE_BRAND_NAME
ENV VITE_BRAND_SHORT=$VITE_BRAND_SHORT
ENV VITE_BRAND_PERSONAL_TITLE=$VITE_BRAND_PERSONAL_TITLE
ENV VITE_BRAND_TEAM_TITLE=$VITE_BRAND_TEAM_TITLE
ENV VITE_BRAND_SHOW_LOGO=$VITE_BRAND_SHOW_LOGO
ENV VITE_PWA_PERSONAL_NAME=$VITE_PWA_PERSONAL_NAME
ENV VITE_PWA_TEAM_NAME=$VITE_PWA_TEAM_NAME
ENV VITE_COPYRIGHT_TEXT=$VITE_COPYRIGHT_TEXT
ENV VITE_ICP_RECORD_TEXT=$VITE_ICP_RECORD_TEXT
ENV VITE_ICP_RECORD_URL=$VITE_ICP_RECORD_URL
ENV VITE_PUBLIC_SECURITY_RECORD_TEXT=$VITE_PUBLIC_SECURITY_RECORD_TEXT
ENV VITE_PUBLIC_SECURITY_RECORD_URL=$VITE_PUBLIC_SECURITY_RECORD_URL
ENV VITE_FEATURE_EDA_ENABLED=$VITE_FEATURE_EDA_ENABLED
ENV VITE_AUTH_IDLE_TIMEOUT_MINUTES=$VITE_AUTH_IDLE_TIMEOUT_MINUTES
ENV VITE_AUTH_MAX_SESSION_HOURS=$VITE_AUTH_MAX_SESSION_HOURS
COPY frontend/package.json ./
COPY frontend/package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci
COPY frontend .
RUN npm run build

FROM componentwarehouse-frontend:latest AS existing-downloads

FROM nginx:1.27-alpine

COPY frontend/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=web-build /app/dist/personal /usr/share/nginx/html/component-warehouse/personal
COPY --from=web-build /app/dist/team /usr/share/nginx/html/component-warehouse/team
COPY --from=existing-downloads /usr/share/nginx/html/component-warehouse/downloads/ /usr/share/nginx/html/component-warehouse/downloads/
RUN chmod -R a+rX /usr/share/nginx/html/component-warehouse

EXPOSE 80
