FROM nginxinc/nginx-unprivileged:stable-alpine
USER root
RUN apk upgrade --no-cache
COPY mvp/ /usr/share/nginx/html/
USER nginx
EXPOSE 8080