import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var serverURLString: String {
        didSet {
            UserDefaults.standard.set(serverURLString, forKey: Self.serverURLKey)
        }
    }

    @Published var credentialsDraft = CredentialsDraft()
    @Published var authCode = ""
    @Published var pin = ""
    @Published var savePinAfterRefresh = true
    @Published var pendingLoginURL: URL?
    @Published var authStatus: AuthStatus?
    @Published var tokenStatus: TokenStatus?
    @Published var savedCredentials: FyersCredentials?
    @Published var authMessage: String?
    @Published var authError: String?
    @Published var isRefreshingAuth = false
    @Published var isSubmittingAuthAction = false

    @Published var watchlistSummary: WatchlistSummary?
    @Published var globalWatchlist: GlobalContinuousWatchlist?
    @Published var watchlistError: String?
    @Published var isRefreshingWatchlist = false

    @Published var positions: [Position] = []
    @Published var positionsError: String?
    @Published var isRefreshingPositions = false

    @Published var portfolioSummary: PortfolioSummary?
    @Published var portfolioInstruments: PortfolioInstrumentSummary?
    @Published var portfolioPeriod: PortfolioPeriod = .daily
    @Published var portfolioError: String?
    @Published var isRefreshingPortfolio = false

    @Published var agentStatus: AgentStatus?
    @Published var strategyControls: [StrategyControl] = []
    @Published var agentEvents: [AgentEvent] = []
    @Published var agentMessage: String?
    @Published var agentError: String?
    @Published var isRefreshingAgent = false
    @Published var isSubmittingAgentAction = false

    private static let serverURLKey = "nifty.mobile.serverURL"

    init() {
        serverURLString = UserDefaults.standard.string(forKey: Self.serverURLKey) ?? "http://127.0.0.1:8000"
    }

    func consumePendingLoginURL() {
        pendingLoginURL = nil
    }

    func refreshAuth() async {
        isRefreshingAuth = true
        authError = nil
        defer { isRefreshingAuth = false }

        do {
            let client = try makeClient()
            async let status: AuthStatus = client.get("auth/status")
            async let token: TokenStatus = client.get("auth/token-status")
            async let credentials: FyersCredentials = client.get("auth/credentials")

            authStatus = try await status
            tokenStatus = try await token
            savedCredentials = try await credentials

            if credentialsDraft.appID.isEmpty {
                credentialsDraft.appID = savedCredentials?.appID ?? ""
            }
            if credentialsDraft.redirectURI.isEmpty || credentialsDraft.redirectURI == CredentialsDraft().redirectURI {
                credentialsDraft.redirectURI = savedCredentials?.redirectURI ?? CredentialsDraft().redirectURI
            }
        } catch {
            authError = error.localizedDescription
        }
    }

    func saveAndLogin() async {
        await runAuthAction {
            let client = try makeClient()
            let payload = CredentialsPayload(
                appID: credentialsDraft.appID.trimmingCharacters(in: .whitespacesAndNewlines),
                secretKey: credentialsDraft.secretKey.trimmingCharacters(in: .whitespacesAndNewlines),
                redirectURI: credentialsDraft.redirectURI.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            let response: SaveAndLoginResponse = try await client.post("auth/save-and-login", body: payload)
            authMessage = response.message
            if let raw = response.loginURL, let url = URL(string: raw) {
                pendingLoginURL = url
            }
            await refreshAuth()
        }
    }

    func openSavedLoginURL() async {
        await runAuthAction {
            let client = try makeClient()
            let response: AuthLoginURL = try await client.get("auth/login-url")
            if let url = URL(string: response.url) {
                pendingLoginURL = url
                authMessage = "Opened the latest broker login URL."
            }
        }
    }

    func submitManualAuthCode() async {
        await runAuthAction {
            let client = try makeClient()
            let response: ManualAuthResponse = try await client.post(
                "auth/manual-code",
                body: AuthCodePayload(authCode: authCode.trimmingCharacters(in: .whitespacesAndNewlines))
            )
            authMessage = response.message
            if response.authenticated {
                authCode = ""
            }
            await refreshAuth()
        }
    }

    func autoRefreshToken() async {
        await runAuthAction {
            let client = try makeClient()
            let response: AutoRefreshResponse = try await client.post("auth/auto-refresh", body: EmptyPayload())
            authMessage = response.message
            await refreshAuth()
        }
    }

    func refreshTokenWithPin() async {
        await runAuthAction {
            let client = try makeClient()
            let response: TokenRefreshResponse = try await client.post(
                "auth/refresh",
                body: PinPayload(pin: pin.trimmingCharacters(in: .whitespacesAndNewlines))
            )
            authMessage = response.message
            await refreshAuth()
        }
    }

    func savePin() async {
        await runAuthAction {
            let client = try makeClient()
            let response: SavePinResponse = try await client.post(
                "auth/save-pin",
                body: SavePinPayload(
                    pin: pin.trimmingCharacters(in: .whitespacesAndNewlines),
                    savePin: savePinAfterRefresh
                )
            )
            authMessage = response.message
            await refreshAuth()
        }
    }

    func logout() async {
        await runAuthAction {
            let client = try makeClient()
            let response: ActionResponse = try await client.post("auth/logout", body: EmptyPayload())
            authMessage = response.message
            await refreshAuth()
        }
    }

    func refreshWatchlist() async {
        isRefreshingWatchlist = true
        watchlistError = nil
        defer { isRefreshingWatchlist = false }

        do {
            let client = try makeClient()
            async let local: WatchlistSummary = client.get("watchlist/summary")
            async let global: GlobalContinuousWatchlist = client.get("watchlist/global/continuous")
            watchlistSummary = try await local
            globalWatchlist = try await global
        } catch {
            watchlistError = error.localizedDescription
        }
    }

    func refreshPositions() async {
        isRefreshingPositions = true
        positionsError = nil
        defer { isRefreshingPositions = false }

        do {
            let client = try makeClient()
            positions = try await client.get("positions")
        } catch {
            positionsError = error.localizedDescription
        }
    }

    func refreshPortfolio() async {
        isRefreshingPortfolio = true
        portfolioError = nil
        defer { isRefreshingPortfolio = false }

        do {
            let client = try makeClient()
            async let summary: PortfolioSummary = client.get("portfolio")
            async let instruments: PortfolioInstrumentSummary = client.get("portfolio/instruments?period=\(portfolioPeriod.rawValue)")
            portfolioSummary = try await summary
            portfolioInstruments = try await instruments
        } catch {
            portfolioError = error.localizedDescription
        }
    }

    func refreshAgent() async {
        isRefreshingAgent = true
        agentError = nil
        defer { isRefreshingAgent = false }

        do {
            let client = try makeClient()
            async let status: AgentStatus = client.get("agent/status")
            async let controlsResponse: StrategyControlsResponse = client.get("agent/strategy-controls")
            async let events: [AgentEvent] = client.get("agent/events?limit=40")
            agentStatus = try await status
            let controls = try await controlsResponse
            strategyControls = controls.controls.sorted { $0.name < $1.name }
            agentEvents = try await events
        } catch {
            agentError = error.localizedDescription
        }
    }

    func startAgent() async {
        await runAgentAction {
            let client = try makeClient()
            let response: ActionResponse = try await client.post("agent/start", body: AgentStartRequest.defaults)
            agentMessage = response.message
            await refreshAgent()
        }
    }

    func stopAgent() async {
        await performAgentAction(path: "agent/stop")
    }

    func pauseAgent() async {
        await performAgentAction(path: "agent/pause")
    }

    func resumeAgent() async {
        await performAgentAction(path: "agent/resume")
    }

    func setStrategyEnabled(_ strategy: String, enabled: Bool) async {
        await runAgentAction {
            let client = try makeClient()
            let response: ActionResponse = try await client.post(
                "agent/strategy-controls",
                body: AgentToggleRequest(strategy: strategy, enabled: enabled)
            )
            agentMessage = response.message
            await refreshAgent()
        }
    }

    func poll(every seconds: Double, action: @escaping @Sendable () async -> Void) async {
        await action()
        while !Task.isCancelled {
            let nanoseconds = UInt64(seconds * 1_000_000_000)
            try? await Task.sleep(nanoseconds: nanoseconds)
            await action()
        }
    }

    private func performAgentAction(path: String) async {
        await runAgentAction {
            let client = try makeClient()
            let response: ActionResponse = try await client.post(path, body: EmptyPayload())
            agentMessage = response.message
            await refreshAgent()
        }
    }

    private func runAuthAction(_ operation: () async throws -> Void) async {
        isSubmittingAuthAction = true
        authError = nil
        defer { isSubmittingAuthAction = false }

        do {
            try await operation()
        } catch {
            authError = error.localizedDescription
        }
    }

    private func runAgentAction(_ operation: () async throws -> Void) async {
        isSubmittingAgentAction = true
        agentError = nil
        defer { isSubmittingAgentAction = false }

        do {
            try await operation()
        } catch {
            agentError = error.localizedDescription
        }
    }

    private func makeClient() throws -> APIClient {
        try APIClient(serverURLString: serverURLString)
    }
}

private struct EmptyPayload: Encodable {}
