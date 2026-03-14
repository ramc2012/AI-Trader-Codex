# Sub-Second Agent Roadmap

## Goal

Move the app from a scan-driven agent to an event-driven execution lane with
sub-second internal reaction time for supported strategies, while keeping the
current terminal UX and control plane stable.

## Current bottlenecks

- The agent sleeps and scans symbols sequentially in `src/agent/trading_agent.py`.
- Market data can still be fetched from caches, TimescaleDB, or REST inside the
  decision path.
- Broker submit is synchronous and order-state updates are not socket-driven.
- UI and analytics concerns are mixed into the same runtime path.

## Target architecture

- Terminal/UI: Next.js + React + WebSocket
- Control plane: FastAPI + Python
- Execution core: Rust
- Hot transport: NATS Core + JetStream
- Durable stream/replay: Kafka
- App state: PostgreSQL / TimescaleDB
- Analytics/query plane: ClickHouse
- Raw tick archive and replay research: QuestDB
- Cache and fast key/value state: Redis

## Why both Kafka and QuestDB stay in the plan

- NATS handles low-latency internal fan-out well, but Kafka remains useful for
  durable replay, downstream consumers, and batch-oriented analytics pipelines.
- ClickHouse is the right main terminal analytics store, but QuestDB is still
  valuable if the team decides to retain dense raw tick and order-book data for
  replay, market-microstructure research, and feed-quality audits.

## Phases

### Phase 1: telemetry and optional infra

- Add optional `docker-compose.subsecond.yml` services for NATS, Kafka,
  ClickHouse, and QuestDB.
- Add backend settings for the new transport and storage layers.
- Expose hot-path timing in `/api/v1/agent/status`.

### Phase 2: event-driven Python pilot

- Stop using `sleep + full scan` for the crypto pilot path.
- Build rolling bars and indicators from the live tick stream.
- Trigger strategies on tick, 1-second, or bar-close events.
- Remove DB and REST lookups from the decision path.
- Move order-state updates to broker sockets rather than polling.

### Phase 3: Rust execution core

- Create a separate Rust service for feed ingestion, incremental indicators,
  risk checks, and order intent generation.
- Publish `ticks`, `bars`, `signals`, `orders`, and `fills` over NATS.
- Mirror durable execution events into Kafka for replay and downstream
  consumers.

### Phase 4: analytics split

- Keep PostgreSQL / TimescaleDB for application state and smaller market-data
  tables.
- Move terminal analytics, scans, and latency dashboards to ClickHouse.
- Mirror raw feed capture into QuestDB only when dense replay becomes a real
  product requirement.

## Acceptance targets

- Tick/bar-close to signal: p99 under 100 ms
- Signal to risk verdict: p99 under 20 ms
- Risk verdict to order submit start: p99 under 30 ms
- Broker acknowledgements measured separately as external latency

## Compose usage

Run the current app plus the optional sub-second stack locally with:

```bash
docker compose -f docker-compose.yml -f docker-compose.subsecond.yml up -d
```

This overlay is intentionally non-breaking: the current Python agent still
runs, while NATS, Kafka, ClickHouse, and QuestDB are brought up for the next
implementation slices.
