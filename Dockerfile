FROM nginx:alpine
COPY . /usr/share/nginx/html
RUN cd /usr/share/nginx/html && rm -rf Dockerfile docker-compose.yml .dockerignore .git .nojekyll
EXPOSE 80
