import SwiftUI

struct PortfolioView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ScreenBackdrop {
            HeroHeader(
                eyebrow: "Capital",
                title: "Portfolio",
                subtitle: "Track aggregate P&L, period performance, and instrument-level contribution in INR."
            )

            if let error = model.portfolioError {
                EmptyPanel(title: "Portfolio Unavailable", message: error)
            }

            if let summary = model.portfolioSummary {
                GlassCard {
                    VStack(alignment: .leading, spacing: 14) {
                        Text("Portfolio Snapshot")
                            .font(.headline)

                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                            MetricTile(label: "Positions", value: String(summary.positionCount), accent: .teal)
                            MetricTile(label: "Market Value", value: DisplayFormatter.currency(summary.totalMarketValueInr ?? summary.totalMarketValue), accent: .indigo)
                            MetricTile(label: "Unrealized", value: DisplayFormatter.signedCurrency(summary.totalUnrealizedPnlInr ?? summary.totalUnrealizedPnl), accent: (summary.totalUnrealizedPnlInr ?? summary.totalUnrealizedPnl) >= 0 ? .green : .red)
                            MetricTile(label: "Realized", value: DisplayFormatter.signedCurrency(summary.totalRealizedPnlInr ?? summary.totalRealizedPnl), accent: (summary.totalRealizedPnlInr ?? summary.totalRealizedPnl) >= 0 ? .green : .red)
                        }

                        HStack {
                            Text("Net P&L")
                                .font(.subheadline.weight(.medium))
                            Spacer()
                            Text(DisplayFormatter.signedCurrency(summary.totalPnlInr ?? summary.totalPnl))
                                .font(.title2.weight(.bold))
                                .foregroundStyle((summary.totalPnlInr ?? summary.totalPnl) >= 0 ? Color.green : Color.red)
                        }
                    }
                }
            }

            GlassCard {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Text("Instrument Performance")
                            .font(.headline)
                        Spacer()
                        Picker("Period", selection: $model.portfolioPeriod) {
                            ForEach(PortfolioPeriod.allCases) { period in
                                Text(period.rawValue.capitalized).tag(period)
                            }
                        }
                        .pickerStyle(.segmented)
                        .frame(maxWidth: 260)
                        .onChange(of: model.portfolioPeriod) { _, _ in
                            Task { await model.refreshPortfolio() }
                        }
                    }

                    if let instruments = model.portfolioInstruments {
                        ForEach(instruments.rows.prefix(12)) { row in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text(row.symbol)
                                        .font(.subheadline.weight(.semibold))
                                    Spacer()
                                    Text(DisplayFormatter.signedCurrency(row.netPnlInr))
                                        .font(.subheadline.weight(.semibold))
                                        .foregroundStyle(row.netPnlInr >= 0 ? Color.green : Color.red)
                                }
                                HStack {
                                    Text("\(row.trades) trade(s)")
                                    Text("Open qty \(row.openQuantity)")
                                    Text("Avg hold \(Int(row.avgHoldMinutes))m")
                                }
                                .font(.caption)
                                .foregroundStyle(Color.secondary)
                            }
                            .padding(.vertical, 6)
                        }
                    } else {
                        Text("No instrument history loaded yet.")
                            .font(.subheadline)
                            .foregroundStyle(Color.secondary)
                    }
                }
            }
        }
        .navigationTitle("Portfolio")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await model.refreshPortfolio()
        }
        .task(id: "\(model.serverURLString)-\(model.portfolioPeriod.rawValue)") {
            await model.poll(every: 7) {
                await model.refreshPortfolio()
            }
        }
    }
}
