# kitshn 2 sends every request of riffle.yarden-zamir.com to one socket. This Caddy is the router that the KitSHn 1
# host Caddy was: /auth/* to oauth2-proxy, the rest to the app, without the identity headers of the client.
FROM caddy:2-alpine
# Not named Caddyfile: .gitignore drops that name, the generated file of KitSHn 1.
COPY router.Caddyfile /etc/caddy/Caddyfile
