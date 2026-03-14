# Execution Core

This is the first standalone Rust service for the sub-second architecture.

Current scope:

- consumes hot-path NATS subjects
  - `ai_trader.market.ticks`
  - `ai_trader.market.bars`
  - `ai_trader.execution.events`
- derives EMA-crossover signal candidates from configured bar timeframes
- publishes derived candidates to `ai_trader.execution.signals`
- maintains in-memory stream counters, latest signal candidates, and last-seen symbol state
- exposes:
  - `GET /health`
  - `GET /stats`
  - `GET /signals`
  - `GET /symbols/:symbol`

Runtime knobs:

- `EXECUTION_CORE_SIGNAL_TIMEFRAMES` default `1,3,5`
- `EXECUTION_CORE_EMA_FAST_PERIOD` default `5`
- `EXECUTION_CORE_EMA_SLOW_PERIOD` default `9`
- `EXECUTION_CORE_SIGNAL_COOLDOWN_SECONDS` default `30`

Current non-goals:

- broker-aware order intent generation
- broker routing
- risk verdicts
- replacing the Python execution lane end-to-end

Those remain the next slices after this sidecar boundary is live.
