import Foundation

enum JSONValue: Codable, Sendable, Equatable {
    case string(String)
    case number(Double)
    case integer(Int)
    case bool(Bool)
    case array([JSONValue])
    case object([String: JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .integer(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON value")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case let .string(value):
            try container.encode(value)
        case let .number(value):
            try container.encode(value)
        case let .integer(value):
            try container.encode(value)
        case let .bool(value):
            try container.encode(value)
        case let .array(value):
            try container.encode(value)
        case let .object(value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }

    var displayText: String {
        switch self {
        case let .string(value):
            return value
        case let .number(value):
            return String(value)
        case let .integer(value):
            return String(value)
        case let .bool(value):
            return value ? "true" : "false"
        case let .array(values):
            return values.map(\.displayText).joined(separator: ", ")
        case let .object(value):
            return value.map { "\($0.key): \($0.value.displayText)" }.sorted().joined(separator: ", ")
        case .null:
            return ""
        }
    }
}

typealias JSONDictionary = [String: JSONValue]

struct CredentialsDraft: Sendable {
    var appID: String = ""
    var secretKey: String = ""
    var redirectURI: String = "https://trade.fyers.in/api-login/redirect-uri/index.html"
}

struct CredentialsPayload: Encodable {
    let appID: String
    let secretKey: String
    let redirectURI: String

    enum CodingKeys: String, CodingKey {
        case appID = "app_id"
        case secretKey = "secret_key"
        case redirectURI = "redirect_uri"
    }
}

struct AuthCodePayload: Encodable {
    let authCode: String

    enum CodingKeys: String, CodingKey {
        case authCode = "auth_code"
    }
}

struct PinPayload: Encodable {
    let pin: String
}

struct SavePinPayload: Encodable {
    let pin: String
    let savePin: Bool

    enum CodingKeys: String, CodingKey {
        case pin
        case savePin = "save_pin"
    }
}

struct AuthStatus: Decodable, Sendable {
    let authenticated: Bool
    let profile: JSONDictionary?
    let appConfigured: Bool
}

struct AuthLoginURL: Decodable, Sendable {
    let url: String
}

struct SaveAndLoginResponse: Decodable, Sendable {
    let success: Bool
    let message: String
    let loginURL: String?
}

struct ManualAuthResponse: Decodable, Sendable {
    let success: Bool
    let message: String
    let authenticated: Bool
}

struct AutoRefreshResponse: Decodable, Sendable {
    let success: Bool
    let message: String
    let refreshed: Bool
    let needsFullReauth: Bool?
}

struct TokenStatus: Decodable, Sendable {
    let accessTokenValid: Bool
    let accessTokenExpiresInHours: Double?
    let refreshTokenValid: Bool
    let refreshTokenExpiresInDays: Double?
    let needsFullReauth: Bool
    let hasSavedPin: Bool
}

struct TokenRefreshResponse: Decodable, Sendable {
    let success: Bool
    let message: String
    let accessTokenExpiresAt: String?
    let refreshTokenExpiresInDays: Double?
    let needsFullReauth: Bool
}

struct SavePinResponse: Decodable, Sendable {
    let success: Bool
    let message: String
    let pinSaved: Bool
}

struct FyersCredentials: Decodable, Sendable {
    let appID: String
    let redirectURI: String
    let configured: Bool
}

struct ActionResponse: Decodable, Sendable {
    let success: Bool?
    let message: String
    let state: String?
}

struct Position: Identifiable, Decodable, Sendable {
    var id: String { symbol }

    let symbol: String
    let quantity: Int
    let side: String
    let avgPrice: Double
    let currentPrice: Double
    let unrealizedPnl: Double
    let unrealizedPnlPct: Double
    let marketValue: Double
    let strategyTag: String
    let entryTime: String?
    let currency: String?
    let currencySymbol: String?
    let unrealizedPnlInr: Double?
    let marketValueInr: Double?
}

struct PortfolioCurrencyBreakdown: Decodable, Sendable {
    let marketValue: Double
    let unrealizedPnl: Double
    let realizedPnl: Double
    let marketValueInr: Double
    let unrealizedPnlInr: Double
    let realizedPnlInr: Double
    let currencySymbol: String
    let fxToInr: Double
}

struct PortfolioMarketBreakdown: Decodable, Sendable {
    let openPositions: Int
    let closedTrades: Int
    let marketValueInr: Double
    let unrealizedPnlInr: Double
    let realizedPnlInr: Double
    let netPnlInr: Double
}

struct PortfolioSummary: Decodable, Sendable {
    let positionCount: Int
    let totalMarketValue: Double
    let totalUnrealizedPnl: Double
    let totalRealizedPnl: Double
    let totalPnl: Double
    let totalMarketValueInr: Double?
    let totalUnrealizedPnlInr: Double?
    let totalRealizedPnlInr: Double?
    let totalPnlInr: Double?
    let baseCurrency: String?
    let usdInrRate: Double?
    let currencyBreakdown: [String: PortfolioCurrencyBreakdown]?
    let marketBreakdown: [String: PortfolioMarketBreakdown]?
}

enum PortfolioPeriod: String, CaseIterable, Identifiable, Codable, Sendable {
    case daily
    case week
    case month
    case year

    var id: String { rawValue }
}

struct InstrumentPerformanceRow: Identifiable, Decodable, Sendable {
    var id: String { symbol }

    let symbol: String
    let currency: String
    let currencySymbol: String
    let trades: Int
    let wins: Int
    let losses: Int
    let realizedPnlInr: Double
    let unrealizedPnlInr: Double
    let netPnlInr: Double
    let avgHoldMinutes: Double
    let lastTradeTime: String?
    let openQuantity: Int
    let openMarketValueInr: Double
}

struct PortfolioInstrumentSummary: Decodable, Sendable {
    let period: PortfolioPeriod
    let fromTime: String
    let toTime: String
    let totalInstruments: Int
    let totalTrades: Int
    let totalRealizedPnlInr: Double
    let totalUnrealizedPnlInr: Double
    let totalNetPnlInr: Double
    let rows: [InstrumentPerformanceRow]
}

struct MarketDataSnapshot: Decodable, Sendable {
    let symbol: String
    let name: String?
    let ltp: Double
    let open: Double
    let high: Double
    let low: Double
    let close: Double
    let volume: Int
    let change: Double?
    let changePct: Double?
    let timestamp: String?
}

struct WatchlistIndexItem: Identifiable, Decodable, Sendable {
    var id: String { name }

    let name: String
    let displayName: String
    let spot: MarketDataSnapshot
    let futures: MarketDataSnapshot
}

struct WatchlistSummary: Decodable, Sendable {
    let timestamp: String
    let totalCount: Int
    let indices: [WatchlistIndexItem]
}

struct GlobalUSUnderlying: Identifiable, Decodable, Sendable {
    var id: String { symbol }

    let symbol: String
    let name: String
    let price: Double?
    let change: Double?
    let changePct: Double?
    let volume: Int?
    let currency: String?
    let market: String?
}

struct GlobalUSOptionFocus: Identifiable, Decodable, Sendable {
    var id: String { symbol }

    let symbol: String
    let name: String
    let price: Double?
    let changePct: Double?
    let expiry: String?
    let atmStrike: Double?
    let callLast: Double?
    let callIv: Double?
    let callOi: Double?
    let putLast: Double?
    let putIv: Double?
    let putOi: Double?
}

struct GlobalCryptoItem: Identifiable, Decodable, Sendable {
    var id: String { symbol }

    let symbol: String
    let name: String
    let priceUsd: Double
    let changePct24h: Double
    let volume24h: Double
    let marketCap: Double
    let rank: Int
    let source: String
}

struct GlobalContinuousWatchlist: Decodable, Sendable {
    let timestamp: String
    let usUnderlyings: [GlobalUSUnderlying]
    let usOptions: [GlobalUSOptionFocus]
    let cryptoTop10: [GlobalCryptoItem]
    let sources: [String: String]
    let errors: [String]?
    let stale: Bool?
    let cacheAgeSeconds: Double?
}

struct StrategyControl: Identifiable, Decodable, Sendable {
    var id: String { name }

    let name: String
    let enabled: Bool
}

struct StrategyControlsResponse: Decodable, Sendable {
    let controls: [StrategyControl]
}

struct AgentStatus: Decodable, Sendable {
    let state: String
    let paperMode: Bool
    let uptimeSeconds: Double
    let currentCycle: Int
    let symbols: [String]
    let usSymbols: [String]?
    let cryptoSymbols: [String]?
    let activeStrategies: [String]
    let activeSessions: [String]?
    let executionTimeframes: [String]?
    let referenceTimeframes: [String]?
    let telegramStatusIntervalMinutes: Int?
    let positionsCount: Int
    let dailyPnl: Double
    let totalSignals: Int
    let totalTrades: Int
    let lastScanTime: String?
    let emergencyStop: Bool?
    let error: String?
}

struct AgentEvent: Identifiable, Decodable, Sendable {
    let eventID: String
    let eventType: String
    let timestamp: String
    let title: String
    let message: String
    let severity: String
    let metadata: JSONDictionary?

    var id: String { eventID }
}

struct AgentToggleRequest: Encodable {
    let strategy: String
    let enabled: Bool
}

struct AgentStartRequest: Encodable, Sendable {
    let symbols: [String]
    let usSymbols: [String]
    let cryptoSymbols: [String]
    let tradeNseWhenOpen: Bool
    let tradeUsWhenOpen: Bool
    let tradeUsOptions: Bool
    let tradeCrypto24X7: Bool
    let strategies: [String]
    let scanIntervalSeconds: Int
    let paperMode: Bool
    let capital: Double
    let maxDailyLossPct: Double
    let timeframe: String
    let executionTimeframes: [String]
    let referenceTimeframes: [String]
    let telegramStatusIntervalMinutes: Int

    enum CodingKeys: String, CodingKey {
        case symbols
        case usSymbols = "us_symbols"
        case cryptoSymbols = "crypto_symbols"
        case tradeNseWhenOpen = "trade_nse_when_open"
        case tradeUsWhenOpen = "trade_us_when_open"
        case tradeUsOptions = "trade_us_options"
        case tradeCrypto24X7 = "trade_crypto_24x7"
        case strategies
        case scanIntervalSeconds = "scan_interval_seconds"
        case paperMode = "paper_mode"
        case capital
        case maxDailyLossPct = "max_daily_loss_pct"
        case timeframe
        case executionTimeframes = "execution_timeframes"
        case referenceTimeframes = "reference_timeframes"
        case telegramStatusIntervalMinutes = "telegram_status_interval_minutes"
    }

    static let defaults = AgentStartRequest(
        symbols: [
            "NSE:NIFTY50-INDEX",
            "NSE:NIFTYBANK-INDEX",
            "NSE:FINNIFTY-INDEX",
            "NSE:NIFTYMIDCAP50-INDEX",
            "BSE:SENSEX-INDEX",
        ],
        usSymbols: [
            "US:SPY",
            "US:QQQ",
            "US:DIA",
            "US:IWM",
            "US:AAPL",
            "US:AMZN",
            "US:JPM",
            "US:XOM",
            "US:UNH",
            "US:CAT",
        ],
        cryptoSymbols: [
            "CRYPTO:BTCUSDT",
            "CRYPTO:ETHUSDT",
            "CRYPTO:BNBUSDT",
            "CRYPTO:SOLUSDT",
            "CRYPTO:XRPUSDT",
            "CRYPTO:ADAUSDT",
            "CRYPTO:DOGEUSDT",
            "CRYPTO:AVAXUSDT",
            "CRYPTO:DOTUSDT",
            "CRYPTO:LINKUSDT",
        ],
        tradeNseWhenOpen: true,
        tradeUsWhenOpen: true,
        tradeUsOptions: true,
        tradeCrypto24X7: true,
        strategies: [
            "EMA_Crossover",
            "RSI_Reversal",
            "Supertrend_Breakout",
            "MP_OrderFlow_Breakout",
            "Fractal_Profile_Breakout",
        ],
        scanIntervalSeconds: 30,
        paperMode: true,
        capital: 250_000,
        maxDailyLossPct: 2.0,
        timeframe: "15",
        executionTimeframes: ["3", "5", "15"],
        referenceTimeframes: ["60", "D"],
        telegramStatusIntervalMinutes: 30
    )
}
