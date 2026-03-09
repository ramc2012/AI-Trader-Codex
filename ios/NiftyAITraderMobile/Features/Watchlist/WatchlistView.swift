import SwiftUI

struct WatchlistView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ScreenBackdrop {
            HeroHeader(
                eyebrow: "Markets",
                title: "Live Watchlist",
                subtitle: "Indian index futures, global underlyings, options focus, and top crypto movers from the existing backend feeds."
            )

            if let error = model.watchlistError {
                EmptyPanel(title: "Watchlist Unavailable", message: error)
            }

            if let summary = model.watchlistSummary {
                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("Indian Index Board")
                                .font(.headline)
                            Spacer()
                            Text(DisplayFormatter.relativeDate(summary.timestamp))
                                .font(.caption)
                                .foregroundStyle(Color.secondary)
                        }

                        ForEach(summary.indices) { item in
                            VStack(alignment: .leading, spacing: 10) {
                                HStack {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(item.displayName)
                                            .font(.title3.weight(.semibold))
                                        Text(item.spot.symbol)
                                            .font(.caption)
                                            .foregroundStyle(Color.secondary)
                                    }
                                    Spacer()
                                    StatusCapsule(
                                        text: DisplayFormatter.percent(item.spot.changePct ?? 0),
                                        color: (item.spot.changePct ?? 0) >= 0 ? .green : .red
                                    )
                                }

                                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                                    MetricTile(label: "Spot", value: DisplayFormatter.number(item.spot.ltp), accent: .teal)
                                    MetricTile(label: "Futures", value: DisplayFormatter.number(item.futures.ltp), accent: .indigo)
                                }
                            }
                            .padding(.vertical, 6)
                        }
                    }
                }
            }

            if let global = model.globalWatchlist {
                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("US Underlyings")
                                .font(.headline)
                            Spacer()
                            if global.stale == true {
                                StatusCapsule(text: "Cached", color: .orange)
                            }
                        }

                        ForEach(global.usUnderlyings.prefix(8)) { item in
                            quoteRow(
                                title: item.symbol,
                                subtitle: item.name,
                                value: DisplayFormatter.currency(item.price ?? 0, code: item.currency ?? "USD"),
                                change: item.changePct ?? 0
                            )
                        }
                    }
                }

                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("US Options Focus")
                            .font(.headline)

                        ForEach(global.usOptions.prefix(6)) { item in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(item.symbol)
                                            .font(.subheadline.weight(.semibold))
                                        Text(item.name)
                                            .font(.caption)
                                            .foregroundStyle(Color.secondary)
                                    }
                                    Spacer()
                                    Text(item.expiry ?? "No expiry")
                                        .font(.caption.weight(.medium))
                                        .foregroundStyle(Color.secondary)
                                }

                                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                                    MetricTile(label: "Spot", value: DisplayFormatter.currency(item.price ?? 0, code: "USD"), accent: .teal)
                                    MetricTile(label: "Call", value: DisplayFormatter.currency(item.callLast ?? 0, code: "USD"), accent: .green)
                                    MetricTile(label: "Put", value: DisplayFormatter.currency(item.putLast ?? 0, code: "USD"), accent: .red)
                                }
                            }
                            .padding(.vertical, 6)
                        }
                    }
                }

                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Crypto Top 10")
                            .font(.headline)

                        ForEach(global.cryptoTop10) { item in
                            quoteRow(
                                title: item.symbol,
                                subtitle: item.name,
                                value: DisplayFormatter.currency(item.priceUsd, code: "USD"),
                                change: item.changePct24h
                            )
                        }
                    }
                }
            }
        }
        .navigationTitle("Watchlist")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await model.refreshWatchlist()
        }
        .task(id: model.serverURLString) {
            await model.poll(every: 8) {
                await model.refreshWatchlist()
            }
        }
    }

    @ViewBuilder
    private func quoteRow(title: String, subtitle: String, value: String, change: Double) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(Color.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text(value)
                    .font(.subheadline.weight(.semibold))
                Text(DisplayFormatter.percent(change))
                    .font(.caption.weight(.medium))
                    .foregroundStyle(change >= 0 ? Color.green : Color.red)
            }
        }
        .padding(.vertical, 4)
    }
}
