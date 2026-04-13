FROM nginx:alpine

# Copy all the static frontend assets into standard nginx serving dir
COPY . /usr/share/nginx/html

# Expose standard port 80
EXPOSE 80

# Run nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
