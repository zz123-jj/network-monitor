ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.28-alpine
FROM ${NODE_IMAGE} AS build
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /app
COPY package*.json ./
RUN npm ci --registry="$NPM_REGISTRY" --no-audit --no-fund
COPY . .
RUN npm run build
FROM ${NGINX_IMAGE}
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
