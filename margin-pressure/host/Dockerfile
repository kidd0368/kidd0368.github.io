FROM node:22-alpine
WORKDIR /app/host
COPY --chown=node:node host/package.json host/server.mjs host/frontend.mjs host/input-status.mjs ./
COPY --chown=node:node index.html /app/index.html
COPY --chown=node:node payload.enc /app/payload.enc
ENV NODE_ENV=production HOST=0.0.0.0 PORT=8787
USER node
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD node -e "fetch('http://127.0.0.1:8787/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.mjs"]
