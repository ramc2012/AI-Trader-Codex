# Nifty AI Trading System - Project Brief

## What We're Building

An end-to-end AI-driven automated options trading system for Indian equity derivatives markets (Nifty 50, Bank Nifty, Sensex) using Fyers broker API.

### Core Objectives
- Fully automated directional options trading (naked call/put buying initially)
- Multi-timeframe data collection and analysis (tick to monthly)
- AI/ML-driven signal generation and strategy execution
- Comprehensive risk management and position monitoring
- Advanced technical analysis (indicators, Market Profile, order flow)
- Real-time visualization and performance dashboards

### Future Vision
Evolve into a multi-asset investment manager supporting:
- Multiple option strategies (spreads, iron condors, etc.)
- Futures trading
- Multi-asset portfolio management
- Advanced AI models (deep learning, reinforcement learning)

---

## Tech Stack

### Backend
- **Language**: Python 3.11+
- **Framework**: FastAPI (async web framework)
- **API Client**: Fyers API v3
- **Task Queue**: Celery + Redis
- **WebSocket**: aiohttp for real-time data streaming

### Database
- **Time-series**: TimescaleDB (PostgreSQL extension)
- **Relational**: PostgreSQL 15+
- **Cache**: Redis 7+
- **Storage**: S3-compatible (for data archival)

### AI/ML Stack
- **Deep Learning**: TensorFlow 2.x / PyTorch 2.x
- **Traditional ML**: scikit-learn, XGBoost, LightGBM
- **Data Processing**: pandas, NumPy, TA-Lib
- **Experiment Tracking**: MLflow / Weights & Biases

### Frontend
- **Framework**: React 18+ with TypeScript
- **State Management**: Zustand / Redux Toolkit
- **Charts**: Plotly.js, Lightweight Charts, Recharts
- **UI Components**: shadcn/ui, Tailwind CSS
- **Real-time**: WebSocket client for live updates

### Infrastructure
- **Containerization**: Docker + Docker Compose
- **Orchestration**: Kubernetes (future production)
- **CI/CD**: GitHub Actions
- **Monitoring**: Prometheus + Grafana
- **Logging**: ELK Stack (Elasticsearch, Logstash, Kibana)

---

## Project Structure

```
nifty-ai-trader/
├── src/
│   ├── api/                    # FastAPI application
│   │   ├── main.py            # FastAPI app entry point
│   │   ├── routes/            # API endpoints
│   │   │   ├── market_data.py
│   │   │   ├── trading.py
│   │   │   ├── analytics.py
│   │   │   └── admin.py
│   │   ├── middleware/        # CORS, auth, logging
│   │   └── dependencies.py    # Dependency injection
│   │
│   ├── data/                   # Data collection & processing
│   │   ├── collectors/        # Data collectors
│   │   │   ├── ohlc_collector.py
│   │   │   ├── tick_collector.py
│   │   │   └── option_chain_collector.py
│   │   ├── processors/        # Data cleaning & validation
│   │   └── pipeline/          # ETL pipelines
│   │
│   ├── integrations/          # External API integrations
│   │   ├── fyers_client.py   # Fyers API wrapper
│   │   └── market_data_feed.py
│   │
│   ├── database/              # Database layer
│   │   ├── models.py         # SQLAlchemy models
│   │   ├── schema.sql        # Database schema
│   │   ├── migrations/       # Alembic migrations
│   │   └── operations.py     # CRUD operations
│   │
│   ├── analysis/              # Technical analysis
│   │   ├── indicators/       # Technical indicators
│   │   ├── market_profile.py # Market Profile engine
│   │   ├── order_flow.py     # Order flow analysis
│   │   └── patterns.py       # Pattern recognition
│   │
│   ├── ml/                    # Machine Learning
│   │   ├── features/         # Feature engineering
│   │   ├── models/           # ML model definitions
│   │   ├── training/         # Training pipelines
│   │   ├── inference/        # Prediction engine
│   │   └── evaluation/       # Model evaluation
│   │
│   ├── strategies/            # Trading strategies
│   │   ├── base.py           # Base strategy class
│   │   ├── directional/      # Directional strategies
│   │   ├── signal_generator.py
│   │   └── backtester.py     # Backtesting engine
│   │
│   ├── risk/                  # Risk management
│   │   ├── position_sizer.py
│   │   ├── risk_calculator.py
│   │   ├── limits.py         # Risk limits
│   │   └── greeks_monitor.py
│   │
│   ├── execution/             # Order execution
│   │   ├── order_manager.py  # Order Management System
│   │   ├── position_manager.py
│   │   └── execution_engine.py
│   │
│   ├── monitoring/            # System monitoring
│   │   ├── alerts.py         # Alert system
│   │   ├── health_checks.py
│   │   └── metrics.py        # Performance metrics
│   │
│   ├── utils/                 # Utilities
│   │   ├── logger.py         # Logging configuration
│   │   ├── exceptions.py     # Custom exceptions
│   │   ├── validators.py     # Data validators
│   │   └── helpers.py        # Helper functions
│   │
│   └── config/                # Configuration
│       ├── settings.py       # Application settings
│       ├── constants.py      # Constants
│       └── market_hours.py   # Market timing
│
├── tests/                     # Test suite
│   ├── unit/                 # Unit tests
│   ├── integration/          # Integration tests
│   ├── fixtures/             # Test fixtures
│   └── mocks/                # Mock objects
│
├── scripts/                   # Utility scripts
│   ├── backfill_data.py     # Historical data backfill
│   ├── test_auth.py         # Test authentication
│   └── db_setup.py          # Database initialization
│
├── docs/                      # Documentation
│   ├── api/                  # API documentation
│   ├── architecture/         # Architecture diagrams
│   ├── strategies/           # Strategy documentation
│   └── deployment/           # Deployment guides
│
├── frontend/                  # React frontend (future)
│   ├── src/
│   ├── public/
│   └── package.json
│
├── docker/                    # Docker configurations
│   ├── docker-compose.yml
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   └── init-db/
│
├── config/                    # Configuration files
│   ├── production.env.example
│   ├── development.env.example
│   └── trading_config.yaml
│
├── notebooks/                 # Jupyter notebooks
│   ├── research/             # Strategy research
│   ├── analysis/             # Data analysis
│   └── backtesting/          # Backtest experiments
│
├── .env.example              # Environment variables template
├── .gitignore
├── requirements.txt          # Python dependencies
├── requirements-dev.txt      # Development dependencies
├── pyproject.toml           # Project metadata
├── README.md
├── DEVELOPMENT_PLAN.md      # Detailed development roadmap
└── CURRENT_SPRINT.md        # Current sprint tasks
```

---

## Current Phase: Phase 1 - Foundation

**Timeline**: Weeks 1-3  
**Goal**: Set up data infrastructure and Fyers integration

### Key Deliverables
1. ✅ Working Fyers API authentication and connection
2. ✅ Historical data collection for all timeframes
3. ✅ TimescaleDB setup with optimized schema
4. ✅ Real-time tick data streaming
5. ✅ Basic REST API for data access
6. ✅ Initial technical indicators implementation

---

## Development Principles

### Code Quality
- **Type Safety**: Use type hints throughout (enforced by mypy)
- **Documentation**: Comprehensive docstrings (Google style)
- **Testing**: Minimum 80% code coverage
- **Async First**: Use async/await for all I/O operations
- **Error Handling**: Explicit error handling at every level

### Trading-Specific Standards
- **Reliability**: 99.9% uptime target during market hours
- **Latency**: <100ms for signal generation
- **Data Quality**: Zero tolerance for bad data
- **Auditability**: Complete trade history and decision logging
- **Safety**: Paper trading mandatory before live deployment

### Security
- **Secrets Management**: All credentials in environment variables
- **API Keys**: Never commit to git (use .env files)
- **Database**: Encrypted at rest and in transit
- **API**: JWT-based authentication for admin endpoints
- **Audit**: Log all sensitive operations

---

## Key Requirements & Constraints

### Data Requirements
- **Historical Data**: Minimum 2 years daily, 3 months intraday
- **Storage**: ~500GB for complete dataset (estimated)
- **Retention**: Tick data (7 days), 1min (3 months), daily (forever)
- **Quality**: 99.99% data accuracy requirement

### Performance Requirements
- **Data Ingestion**: Handle 1000+ ticks/second
- **API Latency**: <50ms for cached queries, <500ms for complex
- **Database**: <100ms query time for typical analytics
- **Backtesting**: Test 1 year of strategy in <5 minutes

### Regulatory Compliance
- **SEBI Guidelines**: Full compliance with SEBI regulations
- **Risk Limits**: Hard-coded maximum position limits
- **Audit Trail**: Complete record of all trades and decisions
- **Kill Switch**: Emergency stop functionality

### Fyers API Constraints
- **Rate Limits**: 
  - Historical data: 1 request/second
  - Order placement: 10 requests/second
  - WebSocket: 100 symbols max per connection
- **Authentication**: OAuth 2.0, tokens expire in 24 hours
- **Market Hours**: 9:15 AM - 3:30 PM IST (equity)

---

## Risk Management Philosophy

### Capital Protection
1. **Maximum Daily Loss**: -2% of capital (hard stop)
2. **Maximum Position Size**: 5% of capital per trade
3. **Maximum Open Positions**: 3 concurrent positions
4. **Position Greeks**: Monitor delta, gamma exposure continuously

### Technical Safeguards
1. **Circuit Breakers**: Auto-pause on abnormal conditions
2. **Position Limits**: Hard-coded, cannot be overridden
3. **Sanity Checks**: Validate every order before placement
4. **Manual Override**: Emergency manual control always available

---

## Success Metrics

### System Performance
- **Uptime**: 99.9% during market hours
- **Data Accuracy**: 99.99% correct data
- **Latency**: 95th percentile <100ms
- **Zero Critical Bugs**: In production

### Trading Performance (Target - Year 1)
- **Sharpe Ratio**: >1.5
- **Maximum Drawdown**: <15%
- **Win Rate**: >55%
- **Risk-Adjusted Returns**: Beat Nifty by 5%+

### Development Velocity
- **Phase 1**: Complete in 3 weeks
- **Paper Trading**: 4 weeks validation
- **Live Trading**: Go-live Week 12

---

## References & Resources

### Fyers Documentation
- API Docs: https://api-docs.fyers.in/
- WebSocket: https://api-docs.fyers.in/web-socket/introduction
- Python SDK: https://github.com/fyers-api/fyers-api-v3

### Technical Analysis
- TA-Lib: https://ta-lib.org/
- Market Profile: "Mind Over Markets" by James Dalton
- Order Flow: "Markets in Profile" by Jim Dalton

### Machine Learning
- Time Series Forecasting: https://www.tensorflow.org/tutorials/structured_data/time_series
- Financial ML: "Advances in Financial Machine Learning" by Marcos López de Prado

### Regulations
- SEBI Guidelines: https://www.sebi.gov.in/
- NSE Trading: https://www.nseindia.com/

---

## Next Steps

1. **Read DEVELOPMENT_PLAN.md** for complete technical architecture
2. **Check CURRENT_SPRINT.md** for immediate tasks
3. **Set up development environment** (Python, Docker, IDE)
4. **Get Fyers API credentials** (sandbox + production)
5. **Start Phase 1, Task 1** with Claude Code

---

## Contact & Support

- **Project Lead**: Chinnadurai
- **Repository**: [To be created]
- **Documentation**: See `docs/` directory
- **Issues**: Track in GitHub Issues

---

*Last Updated: February 8, 2025*
*Version: 1.0 - Initial Planning*
