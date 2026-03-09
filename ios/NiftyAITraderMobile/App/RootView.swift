import SwiftUI

struct RootView: View {
    var body: some View {
        TabView {
            NavigationStack {
                LoginView()
            }
            .tabItem {
                Label("Login", systemImage: "key.horizontal")
            }

            NavigationStack {
                WatchlistView()
            }
            .tabItem {
                Label("Watchlist", systemImage: "chart.line.uptrend.xyaxis")
            }

            NavigationStack {
                PositionsView()
            }
            .tabItem {
                Label("Positions", systemImage: "briefcase")
            }

            NavigationStack {
                PortfolioView()
            }
            .tabItem {
                Label("Portfolio", systemImage: "wallet.pass")
            }

            NavigationStack {
                AgentView()
            }
            .tabItem {
                Label("AI Agent", systemImage: "bolt.badge.clock")
            }
        }
        .tint(.teal)
    }
}
