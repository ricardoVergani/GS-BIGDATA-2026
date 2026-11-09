FROM nginxinc/nginx-unprivileged:stable-alpine
COPY mvp/ /usr/share/nginx/html/
USER nginx
EXPOSE 8080