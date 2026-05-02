# AI Creator Studio

Greenfield MVP monorepo for a cloud real-time AI virtual camera platform.

## Apps
- `apps/web`: Next.js studio UI + NextAuth
- `apps/gateway`: Fastify session/billing orchestration
- `apps/signaling`: WebSocket signaling relay
- `apps/worker`: Python worker health/reservation API scaffold

## Quick Start
1. Install dependencies:
   - `npm install`
   - `pip install -r apps/worker/requirements.txt`
2. Copy environment template:
   - `copy .env.example .env` (Windows)
2. Run services:
   - `npm run dev:gateway`
   - `npm run dev:signaling`
   - `npm run dev:web`
   - `npm run dev:worker`

## Local Infra (Docker Compose)
- Start infra + services:
  - `docker compose -f infra/docker/docker-compose.yml up --build`
- Postgres: `localhost:5432`
- Redis: `localhost:6379`
- Gateway: `http://localhost:4000`
- Signaling: `ws://localhost:4001/ws`
- Worker control/WebRTC offer endpoint: `http://localhost:8000`

## Prisma Setup
- Generate Prisma client:
  - `npm --workspace apps/gateway run prisma:generate`
- Apply schema to a local database:
  - `npx prisma db push --schema apps/gateway/prisma/schema.prisma`

## Test Commands
- `npm run test`
- `npm run typecheck`
- `npm run build`

## Gateway Runtime Mode
- If `DATABASE_URL` is present, gateway uses Postgres + Prisma persistence.
- If `DATABASE_URL` is absent, gateway automatically falls back to in-memory state for local smoke runs.

## MVP Notes
- Browser preview + OBS Browser Source URL flow is scaffolded.
- Credit metering and worker reservation are implemented with in-memory stores for MVP bootstrap.
- Replace in-memory stores with Redis/Postgres wiring for production readiness.
