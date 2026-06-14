FROM node:22-alpine AS build

WORKDIR /app
ARG VITE_BASE=/cw/
ENV VITE_BASE=$VITE_BASE
COPY package.json ./
RUN npm config set registry https://registry.npmmirror.com && npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html/cw

EXPOSE 80
