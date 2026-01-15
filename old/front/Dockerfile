# ============================================
# Stage 1: Dependencies - Install node_modules
# ============================================
FROM node:22-alpine AS deps

WORKDIR /code

# Copy only dependency files first for better layer caching
COPY package.json package-lock.json ./

# Install dependencies (cached if package files unchanged)
RUN npm ci --ignore-scripts

# ============================================
# Stage 2: Builder - Build the application
# ============================================
FROM node:22-alpine AS builder

WORKDIR /code

# Copy dependencies from deps stage
COPY --from=deps /code/node_modules ./node_modules

# Copy source files
COPY package.json package-lock.json ./
COPY src/ ./src/
COPY public/ ./public/
COPY next.config.js tailwind.config.ts postcss.config.js tsconfig.json ./

# Set production environment for build
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Build the application
RUN npm run build

# ============================================
# Stage 3: Runner - Production runtime
# ============================================
FROM node:22-alpine AS runner

WORKDIR /code

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Set production environment
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000

# Copy only necessary files for production
COPY --from=builder /code/public ./public
COPY --from=builder --chown=nextjs:nodejs /code/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /code/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]

# ============================================
# Stage 4: Development - For dev environment
# ============================================
FROM node:22-alpine AS development

WORKDIR /code

ENV CI=true
ENV PORT=3000
ENV NODE_ENV=development

# Copy dependency files
COPY package.json package-lock.json ./

# Install all dependencies (including devDependencies)
RUN npm ci

# Copy source files
COPY . .

# Expose port
EXPOSE 3000

CMD ["npm", "run", "dev"]
