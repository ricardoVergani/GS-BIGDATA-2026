FROM nginxinc/nginx-unprivileged:stable-alpine
USER root
RUN apk upgrade --no-cache
COPY mvp/ /usr/share/nginx/html/
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
USER nginx
EXPOSE 8080