FROM node:24-alpine

WORKDIR /app
COPY airgap/control-plane/package.json ./package.json
COPY airgap/control-plane/server.mjs ./server.mjs
COPY airgap/control-plane/public ./public

ENV NODE_ENV=production
ENV PORT=8787
ENV PREXUS_STATE_DIR=/var/lib/prexus

RUN mkdir -p /var/lib/prexus && chown -R node:node /app /var/lib/prexus
USER node
EXPOSE 8787

CMD ["node", "server.mjs"]
