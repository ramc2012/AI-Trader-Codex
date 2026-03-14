use anyhow::{Context, Result};
use async_nats::Client;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    routing::get,
    Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use futures::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    env,
    net::{IpAddr, Ipv4Addr, SocketAddr},
    sync::Arc,
};
use tokio::{
    net::TcpListener,
    sync::{Notify, RwLock},
    task::JoinHandle,
};
use tower_http::trace::TraceLayer;
use tracing::{error, info, warn};

const MAX_LATEST_SIGNALS: usize = 64;

#[derive(Clone)]
struct AppState {
    shared: Arc<RwLock<ExecutionCoreState>>,
}

#[derive(Clone, Debug)]
struct Config {
    bind_addr: IpAddr,
    port: u16,
    nats_url: String,
    nats_stream_prefix: String,
    max_tracked_symbols: usize,
    signal_timeframes: BTreeSet<String>,
    ema_fast_period: usize,
    ema_slow_period: usize,
    signal_cooldown_seconds: i64,
}

impl Config {
    fn from_env() -> Self {
        let ema_fast_period = env::var("EXECUTION_CORE_EMA_FAST_PERIOD")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(5usize);
        let ema_slow_period = env::var("EXECUTION_CORE_EMA_SLOW_PERIOD")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(9usize)
            .max(ema_fast_period + 1);
        Self {
            bind_addr: env::var("EXECUTION_CORE_BIND_ADDR")
                .ok()
                .and_then(|value| value.parse().ok())
                .unwrap_or(IpAddr::V4(Ipv4Addr::UNSPECIFIED)),
            port: env::var("EXECUTION_CORE_PORT")
                .ok()
                .and_then(|value| value.parse().ok())
                .unwrap_or(8081),
            nats_url: env::var("NATS_URL").unwrap_or_else(|_| "nats://localhost:4222".to_string()),
            nats_stream_prefix: env::var("NATS_STREAM_PREFIX").unwrap_or_else(|_| "ai_trader".to_string()),
            max_tracked_symbols: env::var("EXECUTION_CORE_MAX_TRACKED_SYMBOLS")
                .ok()
                .and_then(|value| value.parse().ok())
                .unwrap_or(256),
            signal_timeframes: csv_env("EXECUTION_CORE_SIGNAL_TIMEFRAMES", &["1", "3", "5"]),
            ema_fast_period,
            ema_slow_period,
            signal_cooldown_seconds: env::var("EXECUTION_CORE_SIGNAL_COOLDOWN_SECONDS")
                .ok()
                .and_then(|value| value.parse().ok())
                .unwrap_or(30),
        }
    }

    fn subjects(&self) -> Vec<String> {
        vec![
            format!("{}.market.ticks", self.nats_stream_prefix),
            format!("{}.market.bars", self.nats_stream_prefix),
            format!("{}.execution.events", self.nats_stream_prefix),
        ]
    }

    fn signal_subject(&self) -> String {
        format!("{}.execution.signals", self.nats_stream_prefix)
    }

    fn signal_engine(&self) -> SignalEngineConfig {
        SignalEngineConfig {
            signal_timeframes: self.signal_timeframes.iter().cloned().collect(),
            ema_fast_period: self.ema_fast_period,
            ema_slow_period: self.ema_slow_period,
            signal_cooldown_seconds: self.signal_cooldown_seconds,
        }
    }
}

#[derive(Clone, Debug, Default, Serialize)]
struct StreamCounters {
    total_events: u64,
    market_ticks: u64,
    market_bars: u64,
    execution_events: u64,
    signal_candidates: u64,
    invalid_payloads: u64,
    publish_errors: u64,
}

#[derive(Clone, Debug, Default, Serialize)]
struct SymbolSnapshot {
    market: String,
    last_tick_price: Option<f64>,
    last_tick_time: Option<String>,
    last_bar_close: Option<f64>,
    last_bar_time: Option<String>,
    last_bar_timeframe: Option<String>,
    last_execution_event: Option<String>,
    last_execution_time: Option<String>,
    last_signal_type: Option<String>,
    last_signal_time: Option<String>,
    last_signal_timeframe: Option<String>,
    last_signal_price: Option<f64>,
}

#[derive(Clone, Debug, Serialize)]
struct SignalEngineConfig {
    signal_timeframes: Vec<String>,
    ema_fast_period: usize,
    ema_slow_period: usize,
    signal_cooldown_seconds: i64,
}

#[derive(Clone, Debug, Serialize)]
struct SignalCandidateSummary {
    event_id: String,
    symbol: String,
    market: String,
    timeframe: String,
    signal_type: String,
    price: f64,
    event_time: String,
    ema_fast: f64,
    ema_slow: f64,
}

#[derive(Clone, Debug, Default)]
struct SignalModelState {
    bars_seen: u64,
    ema_fast: Option<f64>,
    ema_slow: Option<f64>,
    last_relation: i8,
    last_signal_at: Option<DateTime<Utc>>,
}

#[derive(Clone, Debug, Serialize)]
struct ExecutionCoreState {
    status: String,
    started_at: String,
    nats_connected: bool,
    nats_url: String,
    subjects: Vec<String>,
    signal_subject: String,
    counters: StreamCounters,
    signal_engine: SignalEngineConfig,
    tracked_symbols: BTreeMap<String, SymbolSnapshot>,
    latest_signals: Vec<SignalCandidateSummary>,
    #[serde(skip)]
    signal_models: BTreeMap<String, SignalModelState>,
}

impl ExecutionCoreState {
    fn new(config: &Config) -> Self {
        Self {
            status: "starting".to_string(),
            started_at: chrono_like_now(),
            nats_connected: false,
            nats_url: config.nats_url.clone(),
            subjects: config.subjects(),
            signal_subject: config.signal_subject(),
            counters: StreamCounters::default(),
            signal_engine: config.signal_engine(),
            tracked_symbols: BTreeMap::new(),
            latest_signals: Vec::new(),
            signal_models: BTreeMap::new(),
        }
    }

    fn mark_connected(&mut self) {
        self.status = "running".to_string();
        self.nats_connected = true;
    }

    fn mark_stopping(&mut self) {
        self.status = "stopping".to_string();
        self.nats_connected = false;
    }

    fn record_invalid_payload(&mut self) {
        self.counters.invalid_payloads += 1;
    }

    fn record_publish_error(&mut self) {
        self.counters.publish_errors += 1;
    }

    fn record_envelope(&mut self, envelope: ExecutionEnvelope, config: &Config) -> Option<PublishedSignalEnvelope> {
        self.counters.total_events += 1;
        let stream = envelope.stream.clone().unwrap_or_else(|| "execution".to_string());
        match stream.as_str() {
            "market_ticks" => self.counters.market_ticks += 1,
            "market_bars" => self.counters.market_bars += 1,
            _ => self.counters.execution_events += 1,
        }

        let Some(symbol) = envelope.symbol.clone().filter(|value| !value.trim().is_empty()) else {
            return None;
        };
        let market = envelope
            .market
            .clone()
            .unwrap_or_else(|| infer_market(&symbol).to_string());
        self.touch_symbol(&symbol, &market, &envelope, config.max_tracked_symbols);

        if stream == "market_bars" {
            return self.evaluate_signal_candidate(&symbol, &market, &envelope, config);
        }
        None
    }

    fn touch_symbol(
        &mut self,
        symbol: &str,
        market: &str,
        envelope: &ExecutionEnvelope,
        max_tracked_symbols: usize,
    ) {
        if !self.tracked_symbols.contains_key(symbol) && self.tracked_symbols.len() >= max_tracked_symbols {
            if let Some(first_key) = self.tracked_symbols.keys().next().cloned() {
                self.tracked_symbols.remove(&first_key);
            }
        }

        let snapshot = self
            .tracked_symbols
            .entry(symbol.to_string())
            .or_insert_with(|| SymbolSnapshot {
                market: market.to_string(),
                ..SymbolSnapshot::default()
            });
        if snapshot.market.is_empty() {
            snapshot.market = market.to_string();
        }

        match envelope.stream.as_deref().unwrap_or("execution") {
            "market_ticks" => {
                snapshot.last_tick_price = envelope.ltp;
                snapshot.last_tick_time = envelope.event_time.clone();
            }
            "market_bars" => {
                snapshot.last_bar_close = envelope.close;
                snapshot.last_bar_time = envelope.event_time.clone();
                snapshot.last_bar_timeframe = envelope.timeframe.clone();
            }
            _ => {
                snapshot.last_execution_event = envelope.event_type.clone();
                snapshot.last_execution_time = envelope.event_time.clone();
            }
        }
    }

    fn evaluate_signal_candidate(
        &mut self,
        symbol: &str,
        market: &str,
        envelope: &ExecutionEnvelope,
        config: &Config,
    ) -> Option<PublishedSignalEnvelope> {
        let timeframe = normalize_token(envelope.timeframe.as_deref())?;
        if !config.signal_timeframes.contains(&timeframe) {
            return None;
        }
        let close = envelope.close?;
        let event_time = envelope
            .event_time
            .clone()
            .unwrap_or_else(chrono_like_now);
        let event_dt = parse_event_time(&event_time).unwrap_or_else(Utc::now);
        let model_key = format!("{symbol}|{timeframe}");
        let model = self.signal_models.entry(model_key).or_default();
        model.bars_seen += 1;
        model.ema_fast = Some(next_ema(model.ema_fast, close, config.ema_fast_period));
        model.ema_slow = Some(next_ema(model.ema_slow, close, config.ema_slow_period));
        let ema_fast = model.ema_fast.unwrap_or(close);
        let ema_slow = model.ema_slow.unwrap_or(close);
        let relation = compare_f64(ema_fast, ema_slow);

        if relation != 0 {
            if model.bars_seen < config.ema_slow_period as u64 {
                model.last_relation = relation;
                return None;
            }

            let crossed = model.last_relation != 0 && relation != model.last_relation;
            let cooldown_ready = model
                .last_signal_at
                .map(|last| (event_dt - last).num_seconds() >= config.signal_cooldown_seconds)
                .unwrap_or(true);
            let previous_relation = model.last_relation;
            model.last_relation = relation;

            if crossed && cooldown_ready {
                let signal_type = if relation > previous_relation { "BUY" } else { "SELL" };
                model.last_signal_at = Some(event_dt);
                let signal = PublishedSignalEnvelope {
                    stream: "execution_signals".to_string(),
                    event_time: event_time.clone(),
                    event_id: format!(
                        "sig:{}:{}:{}:{}",
                        symbol,
                        timeframe,
                        signal_type,
                        event_dt.timestamp_millis()
                    ),
                    source: "execution_core".to_string(),
                    event_type: "signal_candidate".to_string(),
                    signal_type: signal_type.to_string(),
                    symbol: symbol.to_string(),
                    market: market.to_string(),
                    timeframe: timeframe.clone(),
                    strategy: "Rust_EMA_Crossover".to_string(),
                    price: close,
                    payload: json!({
                        "ema_fast": round4(ema_fast),
                        "ema_slow": round4(ema_slow),
                        "bars_seen": model.bars_seen,
                        "cooldown_seconds": config.signal_cooldown_seconds,
                        "bar_close": round4(close),
                    }),
                };
                self.record_signal(signal.clone());
                return Some(signal);
            }
        }

        None
    }

    fn record_signal(&mut self, signal: PublishedSignalEnvelope) {
        self.counters.signal_candidates += 1;
        if let Some(snapshot) = self.tracked_symbols.get_mut(&signal.symbol) {
            snapshot.last_signal_type = Some(signal.signal_type.clone());
            snapshot.last_signal_time = Some(signal.event_time.clone());
            snapshot.last_signal_timeframe = Some(signal.timeframe.clone());
            snapshot.last_signal_price = Some(signal.price);
        }
        self.latest_signals.push(SignalCandidateSummary {
            event_id: signal.event_id,
            symbol: signal.symbol,
            market: signal.market,
            timeframe: signal.timeframe,
            signal_type: signal.signal_type,
            price: round4(signal.price),
            event_time: signal.event_time,
            ema_fast: round4(signal.payload.get("ema_fast").and_then(Value::as_f64).unwrap_or(0.0)),
            ema_slow: round4(signal.payload.get("ema_slow").and_then(Value::as_f64).unwrap_or(0.0)),
        });
        if self.latest_signals.len() > MAX_LATEST_SIGNALS {
            let overflow = self.latest_signals.len() - MAX_LATEST_SIGNALS;
            self.latest_signals.drain(0..overflow);
        }
    }
}

#[derive(Debug, Deserialize)]
struct ExecutionEnvelope {
    stream: Option<String>,
    event_time: Option<String>,
    event_type: Option<String>,
    symbol: Option<String>,
    market: Option<String>,
    timeframe: Option<String>,
    ltp: Option<f64>,
    close: Option<f64>,
    #[allow(dead_code)]
    open: Option<f64>,
    #[allow(dead_code)]
    high: Option<f64>,
    #[allow(dead_code)]
    low: Option<f64>,
    #[allow(dead_code)]
    volume: Option<i64>,
    #[allow(dead_code)]
    payload: Option<Value>,
}

#[derive(Clone, Debug, Serialize)]
struct PublishedSignalEnvelope {
    stream: String,
    event_time: String,
    event_id: String,
    source: String,
    event_type: String,
    signal_type: String,
    symbol: String,
    market: String,
    timeframe: String,
    strategy: String,
    price: f64,
    payload: Value,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: String,
    nats_connected: bool,
    signal_candidates: u64,
}

#[tokio::main]
async fn main() -> Result<()> {
    init_tracing();
    let config = Config::from_env();
    let shared = Arc::new(RwLock::new(ExecutionCoreState::new(&config)));
    let client = async_nats::connect(config.nats_url.clone())
        .await
        .with_context(|| format!("failed to connect to NATS at {}", config.nats_url))?;
    {
        let mut state = shared.write().await;
        state.mark_connected();
    }

    let shutdown = Arc::new(Notify::new());
    let app = Router::new()
        .route("/health", get(health))
        .route("/stats", get(stats))
        .route("/signals", get(latest_signals))
        .route("/symbols/:symbol", get(symbol_snapshot))
        .with_state(AppState {
            shared: Arc::clone(&shared),
        })
        .layer(TraceLayer::new_for_http());

    let bind_addr = SocketAddr::new(config.bind_addr, config.port);
    let listener = TcpListener::bind(bind_addr)
        .await
        .with_context(|| format!("failed to bind execution-core on {}", bind_addr))?;

    let http_shutdown = Arc::clone(&shutdown);
    let mut http_handle = tokio::spawn(async move {
        axum::serve(listener, app.into_make_service())
            .with_graceful_shutdown(async move {
                http_shutdown.notified().await;
            })
            .await
            .context("execution-core http server failed")
    });

    let mut consumers = Vec::new();
    for subject in config.subjects() {
        consumers.push(tokio::spawn(run_subject_consumer(
            client.clone(),
            subject,
            Arc::clone(&shared),
            config.clone(),
        )));
    }

    info!(
        bind_addr = %bind_addr,
        nats_url = %config.nats_url,
        subjects = ?config.subjects(),
        signal_subject = %config.signal_subject(),
        signal_timeframes = ?config.signal_engine().signal_timeframes,
        "execution_core_started"
    );

    let mut http_completed = false;
    tokio::select! {
        result = await_consumer_failure(&mut consumers) => {
            if let Err(error) = result {
                error!(error = %error, "execution_core_consumer_failed");
            }
        }
        result = &mut http_handle => {
            http_completed = true;
            match result {
                Ok(Ok(())) => {}
                Ok(Err(error)) => error!(error = %error, "execution_core_http_failed"),
                Err(error) => error!(error = %error, "execution_core_http_join_failed"),
            }
        }
        _ = shutdown_signal() => {
            info!("execution_core_shutdown_requested");
        }
    }

    {
        let mut state = shared.write().await;
        state.mark_stopping();
    }
    shutdown.notify_waiters();
    for handle in consumers {
        handle.abort();
        let _ = handle.await;
    }
    drop(client);
    if !http_completed {
        let _ = http_handle.await;
    }
    info!("execution_core_stopped");
    Ok(())
}

async fn run_subject_consumer(
    client: Client,
    subject: String,
    shared: Arc<RwLock<ExecutionCoreState>>,
    config: Config,
) -> Result<()> {
    let mut subscription = client
        .subscribe(subject.clone())
        .await
        .with_context(|| format!("failed to subscribe to {}", subject))?;
    let signal_subject = config.signal_subject();
    while let Some(message) = subscription.next().await {
        match serde_json::from_slice::<ExecutionEnvelope>(message.payload.as_ref()) {
            Ok(envelope) => {
                let maybe_signal = {
                    let mut state = shared.write().await;
                    state.record_envelope(envelope, &config)
                };
                if let Some(signal) = maybe_signal {
                    let payload = serde_json::to_vec(&signal).context("failed to encode signal envelope")?;
                    if let Err(error) = client.publish(signal_subject.clone(), payload.into()).await {
                        warn!(error = %error, subject = %signal_subject, "execution_core_signal_publish_failed");
                        let mut state = shared.write().await;
                        state.record_publish_error();
                    } else {
                        info!(
                            subject = %signal_subject,
                            symbol = %signal.symbol,
                            timeframe = %signal.timeframe,
                            signal_type = %signal.signal_type,
                            "execution_core_signal_published"
                        );
                    }
                }
            }
            Err(error) => {
                warn!(subject = %subject, error = %error, "execution_core_invalid_payload");
                let mut state = shared.write().await;
                state.record_invalid_payload();
            }
        }
    }
    Ok(())
}

async fn await_consumer_failure(consumers: &mut Vec<JoinHandle<Result<()>>>) -> Result<()> {
    for consumer in consumers.iter_mut() {
        match consumer.await {
            Ok(Ok(())) => {}
            Ok(Err(error)) => return Err(error),
            Err(error) => return Err(anyhow::anyhow!(error.to_string())),
        }
    }
    Ok(())
}

async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    let snapshot = state.shared.read().await;
    let status = if snapshot.nats_connected {
        "ok".to_string()
    } else {
        "degraded".to_string()
    };
    Json(HealthResponse {
        status,
        nats_connected: snapshot.nats_connected,
        signal_candidates: snapshot.counters.signal_candidates,
    })
}

async fn stats(State(state): State<AppState>) -> Json<ExecutionCoreState> {
    Json(state.shared.read().await.clone())
}

async fn latest_signals(State(state): State<AppState>) -> Json<Vec<SignalCandidateSummary>> {
    Json(state.shared.read().await.latest_signals.clone())
}

async fn symbol_snapshot(
    Path(symbol): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<SymbolSnapshot>, StatusCode> {
    let snapshot = state.shared.read().await;
    snapshot
        .tracked_symbols
        .get(&symbol)
        .cloned()
        .map(Json)
        .ok_or(StatusCode::NOT_FOUND)
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };

    #[cfg(unix)]
    let terminate = async {
        use tokio::signal::unix::{signal, SignalKind};
        if let Ok(mut signal) = signal(SignalKind::terminate()) {
            signal.recv().await;
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {}
        _ = terminate => {}
    }
}

fn init_tracing() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,execution_core=debug".into()),
        )
        .with_target(false)
        .compact()
        .init();
}

fn infer_market(symbol: &str) -> &'static str {
    let token = symbol.trim().to_uppercase();
    if token.starts_with("CRYPTO:") {
        "CRYPTO"
    } else if token.starts_with("US:") || token.starts_with("NASDAQ:") || token.starts_with("NYSE:") {
        "US"
    } else {
        "NSE"
    }
}

fn chrono_like_now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn parse_event_time(value: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|value| value.with_timezone(&Utc))
}

fn normalize_token(value: Option<&str>) -> Option<String> {
    value
        .map(|value| value.trim().to_uppercase())
        .filter(|value| !value.is_empty())
}

fn next_ema(previous: Option<f64>, price: f64, period: usize) -> f64 {
    let alpha = 2.0 / (period as f64 + 1.0);
    previous
        .map(|prev| prev + alpha * (price - prev))
        .unwrap_or(price)
}

fn compare_f64(left: f64, right: f64) -> i8 {
    if left > right {
        1
    } else if left < right {
        -1
    } else {
        0
    }
}

fn csv_env(name: &str, default: &[&str]) -> BTreeSet<String> {
    let value = env::var(name).unwrap_or_else(|_| default.join(","));
    value
        .split(',')
        .map(|token| token.trim().to_uppercase())
        .filter(|token| !token.is_empty())
        .collect()
}

fn round4(value: f64) -> f64 {
    (value * 10_000.0).round() / 10_000.0
}
