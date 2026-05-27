# Stage 1: Build the static assets
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# Stage 2: Serve using Nginx
FROM nginx:alpine

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled static assets from Stage 1
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 8080

# Start Nginx
CMD ["nginx", "-g", "daemon off;"]
