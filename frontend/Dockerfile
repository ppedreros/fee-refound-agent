# Frontend image: build with Node, serve with nginx on port 8080.
# nginx's entrypoint renders /etc/nginx/templates/*.template with envsubst at start, so the
# backend address comes from BACKEND_URL and the same image works locally and on the host.

FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29-alpine
ENV BACKEND_URL=http://backend:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
