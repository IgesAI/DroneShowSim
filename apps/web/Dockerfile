FROM node:22-slim
WORKDIR /repo
COPY package.json package-lock.json* ./
COPY apps/web ./apps/web
COPY packages ./packages
RUN npm install --workspace=@lumina/web --include-workspace-root
WORKDIR /repo/apps/web
EXPOSE 3000
CMD ["npm", "run", "dev"]
