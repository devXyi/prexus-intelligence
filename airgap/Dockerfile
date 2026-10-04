# Air-gap control plane. Build on the CONNECTED side, pin the base image by digest, export with
# `docker save`, and load inside the enclave (see docs/AIRGAP_RUNBOOK.md). No npm dependencies.
FROM node:24-alpine
WORKDIR /app
COPY airgap/control-plane/package.json ./package.json
COPY airgap/control-plane/server.mjs ./server.mjs
COPY airgap/control-plane/lib ./lib
COPY airgap/control-plane/tools ./tools
COPY airgap/control-plane/public ./public
ENV NODE_ENV=production PORT=8787 PREXUS_STATE_DIR=/var/lib/prexus PREXUS_ENV=production PREXUS_BIND=0.0.0.0
RUN mkdir -p /var/lib/prexus && chown -R node:node /app /var/lib/prexus
USER node
EXPOSE 8787
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s CMD node -e "fetch('http://127.0.0.1:8787/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.mjs"]
