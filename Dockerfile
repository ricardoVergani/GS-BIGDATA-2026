FROM nginxinc/nginx-unprivileged:stable-alpine
COPY mvp/ /usr/share/nginx/html/
EXPOSE 8080