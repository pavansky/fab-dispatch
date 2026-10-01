# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.29-alpine
# Security fixes published since the base image was built.
RUN apk upgrade --no-cache
LABEL org.opencontainers.image.source="https://github.com/pavansky/fab-dispatch" \
      org.opencontainers.image.licenses="MIT"
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
