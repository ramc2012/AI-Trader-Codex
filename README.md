# Nifty AI Trader

> AI-driven automated options trading system for Indian equity derivatives markets

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 🎯 Project Overview

An end-to-end automated trading system that:
- Trades Nifty 50, Bank Nifty, and Sensex options
- Uses AI/ML for signal generation and decision making
- Collects and analyzes multi-timeframe market data (tick to monthly)
- Implements comprehensive risk management
- Provides real-time monitoring and visualization

**Current Status**: Phase 1 - Data Infrastructure Foundation

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11 or higher
- Docker and Docker Compose
- Fyers API credentials ([Get them here](https://myapi.fyers.in/))
- Git

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd nifty-ai-trader
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For development
```

4. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env and add your Fyers API credentials
```

5. **Start databases**
```bash
docker-compose up -d
```

6. **Initialize database**
```bash
python scripts/db_setup.py
```

7. **Run the application**
```bash
uvicorn src.api.main:app --reload
```

Visit http://localhost:8000/docs for API documentation

---

## 📁 Project Structure

```
nifty-ai-trader/
├── src/                    # Source code
│   ├── api/               # FastAPI application
│   ├── data/              # Data collection & processing
│   ├── integrations/      # External API integrations
│   ├── database/          # Database models & operations
│   ├── analysis/          # Technical analysis
│   ├── ml/                # Machine learning
│   ├── strategies/        # Trading strategies
│   ├── risk/              # Risk management
│   └── execution/         # Order execution
├── tests/                 # Test suite
├── docs/                  # Documentation
├── scripts/               # Utility scripts
├── config/                # Configuration files
└── docker/                # Docker configurations
```

See [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for detailed architecture.

---

## 📋 Development Roadmap

### Phase 1: Foundation (Weeks 1-3) ⏳ In Progress
- [ ] Fyers API integration
- [ ] Multi-timeframe data collection
- [ ] TimescaleDB setup
- [ ] Real-time tick streaming
- [ ] Basic REST API
- [ ] Core technical indicators

### Phase 2: Analytics (Weeks 4-6)
- [ ] Complete indicator library
- [ ] Market Profile implementation
- [ ] AI feature engineering
- [ ] Backtesting framework
- [ ] Basic dashboard

### Phase 3: Trading System (Weeks 7-9)
- [ ] Risk management module
- [ ] Order Management System
- [ ] Position tracking
- [ ] Paper trading
- [ ] Monitoring & alerts

### Phase 4: Production Ready (Weeks 10-12)
- [ ] Directional strategies implementation
- [ ] Complete dashboard
- [ ] Automated model retraining
- [ ] Production deployment
- [ ] Live trading (after extensive paper trading)

See [CURRENT_SPRINT.md](CURRENT_SPRINT.md) for current tasks.

---

## 🛠️ Tech Stack

**Backend**
- Python 3.11+ (FastAPI framework)
- TimescaleDB (time-series data)
- Redis (caching & queuing)
- Celery (task queue)

**AI/ML**
- TensorFlow / PyTorch
- scikit-learn, XGBoost
- pandas, NumPy

**Frontend** (Future)
- React + TypeScript
- Plotly, Lightweight Charts
- Tailwind CSS

**Infrastructure**
- Docker & Docker Compose
- GitHub Actions (CI/CD)
- Prometheus + Grafana (monitoring)

---

## 📊 Features

### Data Collection
- ✅ Multi-timeframe OHLC (1min to 1month)
- ✅ Real-time tick data streaming
- ✅ Option chain with Greeks
- ✅ Historical data backfill

### Technical Analysis
- ✅ 20+ technical indicators
- ✅ Market Profile
- ✅ Order flow analysis
- ✅ Pattern recognition

### AI/ML
- 🔄 Feature engineering pipeline
- 🔄 LSTM/GRU models for direction prediction
- 🔄 Volatility forecasting
- 🔄 Ensemble methods

### Trading
- 🔄 Directional strategies (call/put buying)
- 🔄 Position sizing algorithms
- 🔄 Risk management
- 🔄 Automated execution

### Monitoring
- 🔄 Real-time dashboard
- 🔄 Performance analytics
- 🔄 Alert system
- 🔄 Trade journal

*Legend: ✅ Planned | 🔄 In Progress | ✅ Complete*

---

## 🔧 Configuration

### Environment Variables

```bash
# Fyers API
FYERS_APP_ID=your_app_id
FYERS_SECRET_KEY=your_secret_key
FYERS_REDIRECT_URI=http://localhost:8000/callback

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/nifty_trader
TIMESCALEDB_URL=postgresql://user:pass@localhost:5432/nifty_trader

# Redis
REDIS_URL=redis://localhost:6379/0

# Environment
ENVIRONMENT=development  # development, staging, production
LOG_LEVEL=INFO

# Trading
PAPER_TRADING=true
MAX_DAILY_LOSS=0.02  # 2% of capital
MAX_POSITION_SIZE=0.05  # 5% of capital
```

### Trading Configuration

See `config/trading_config.yaml` for strategy parameters and risk limits.

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_fyers_client.py

# Run integration tests
pytest tests/integration/

# Run with verbose output
pytest -v
```

---

## 📈 Usage Examples

### Fetch Historical Data

```python
from src.integrations.fyers_client import FyersClient
from src.data.collectors.ohlc_collector import OHLCCollector

# Authenticate
fyers = FyersClient()
await fyers.authenticate()

# Collect data
collector = OHLCCollector(fyers)
data = await collector.fetch_historical(
    symbol='NSE:NIFTY50-INDEX',
    timeframe='1D',
    from_date=date(2024, 1, 1),
    to_date=date(2024, 12, 31)
)

print(data.head())
```

### Calculate Technical Indicators

```python
from src.analysis.indicators import SMA, RSI, MACD

# Calculate indicators
data['SMA_20'] = SMA(data['close'], period=20)
data['RSI_14'] = RSI(data['close'], period=14)
data['MACD'], data['Signal'] = MACD(data['close'])

print(data[['close', 'SMA_20', 'RSI_14']].tail())
```

### Paper Trading

```python
from src.strategies.directional import EMAStrategy
from src.execution.paper_trading import PaperTrader

# Create strategy
strategy = EMAStrategy(
    fast_period=9,
    slow_period=21,
    capital=100000
)

# Run paper trading
trader = PaperTrader(strategy)
await trader.start()
```

---

## 🔐 Security

**⚠️ IMPORTANT**: Never commit sensitive data!

- Use `.env` files for credentials (never commit these)
- Keep API keys secure
- Enable 2FA on Fyers account
- Use paper trading before live trading
- Review all trades in paper mode for minimum 4 weeks

---

## 📚 Documentation

- [Project Brief](PROJECT_BRIEF.md) - High-level overview
- [Development Plan](DEVELOPMENT_PLAN.md) - Complete architecture
- [Current Sprint](CURRENT_SPRINT.md) - Current tasks
- [API Documentation](http://localhost:8000/docs) - Auto-generated API docs
- [Coding Standards](.claudecontext) - Code guidelines

---

## 🤝 Contributing

This is currently a personal project. If you're interested in contributing:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## ⚠️ Disclaimer

**This is an automated trading system. Trading in financial markets involves substantial risk.**

- Use at your own risk
- Start with paper trading
- Validate extensively before live trading
- Never trade more than you can afford to lose
- Past performance does not guarantee future results
- This is not financial advice

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Fyers API for market data and execution
- TimescaleDB for time-series database
- FastAPI for the excellent web framework
- The Python trading community

---

## 📞 Support

For questions or issues:
- Create an issue in GitHub
- Check documentation in `docs/`
- Review example code in `notebooks/`

---

## 🗺️ Roadmap Beyond Phase 1

- Multi-strategy portfolio management
- Options spreads strategies
- Futures trading integration
- Advanced ML models (transformers, RL)
- Multi-asset support (stocks, commodities)
- Mobile app for monitoring
- Community features (strategy sharing)

---

**Built with ❤️ by Chinnadurai**

*Last Updated: February 8, 2025*
