# Frontend image: build the SvelteKit static SPA, serve it with nginx.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Baked into the client bundle; the browser (on the host) reaches the backend here.
ARG VITE_API_BASE=http://localhost:8001
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
