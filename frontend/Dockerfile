FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npx ng build

FROM nginx:alpine
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
