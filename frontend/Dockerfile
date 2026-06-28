FROM node:22-alpine AS web-build

WORKDIR /app
ARG VITE_BRAND_NAME=Component Warehouse
ARG VITE_BRAND_SHORT=Component Warehouse
ARG VITE_BRAND_PERSONAL_TITLE=Component Warehouse · Personal
ARG VITE_BRAND_TEAM_TITLE=Component Warehouse · Team
ARG VITE_BRAND_SHOW_LOGO=0
ARG VITE_FEATURE_EDA_ENABLED=1
ENV VITE_BRAND_NAME=$VITE_BRAND_NAME
ENV VITE_BRAND_SHORT=$VITE_BRAND_SHORT
ENV VITE_BRAND_PERSONAL_TITLE=$VITE_BRAND_PERSONAL_TITLE
ENV VITE_BRAND_TEAM_TITLE=$VITE_BRAND_TEAM_TITLE
ENV VITE_BRAND_SHOW_LOGO=$VITE_BRAND_SHOW_LOGO
ENV VITE_FEATURE_EDA_ENABLED=$VITE_FEATURE_EDA_ENABLED
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
