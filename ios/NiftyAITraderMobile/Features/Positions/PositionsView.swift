import SwiftUI

struct PositionsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ScreenBackdrop {
            HeroHeader(
                eyebrow: "Execution",
                title: "Open Positions",
                subtitle: "Monitor quantity, mark-to-market, and active strategy tags from the trading engine."
            )

            if let error = model.positionsError {
                EmptyPanel(title: "Positions Unavailable", message: error)
            }

            if model.positions.isEmpty, model.positionsError == nil, !model.isRefreshingPositions {
                EmptyPanel(title: "No Open Positions", message: "The paper portfolio is flat right now.")
            }

            ForEach(model.positions) { position in
                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(position.symbol)
                                    .font(.headline)
                                Text(position.strategyTag.isEmpty ? "Manual / unspecified strategy" : position.strategyTag)
                                    .font(.caption)
                                    .foregroundStyle(Color.secondary)
                            }
                            Spacer()
                            StatusCapsule(
                                text: position.side.uppercased(),
                                color: position.side.lowercased() == "long" ? .green : .red
                            )
                        }

                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                            MetricTile(label: "Quantity", value: String(position.quantity), accent: .teal)
                            MetricTile(label: "Market Value", value: DisplayFormatter.currency(position.marketValueInr ?? position.marketValue), accent: .indigo)
                            MetricTile(label: "Average", value: DisplayFormatter.number(position.avgPrice), accent: .orange)
                            MetricTile(label: "Current", value: DisplayFormatter.number(position.currentPrice), accent: .teal)
                        }

                        HStack {
                            Text("Unrealized P&L")
                                .font(.subheadline.weight(.medium))
                            Spacer()
                            Text(DisplayFormatter.signedCurrency(position.unrealizedPnlInr ?? position.unrealizedPnl))
                                .font(.title3.weight(.semibold))
                                .foregroundStyle((position.unrealizedPnlInr ?? position.unrealizedPnl) >= 0 ? Color.green : Color.red)
                        }

                        Text(DisplayFormatter.percent(position.unrealizedPnlPct))
                            .font(.caption.weight(.medium))
                            .foregroundStyle(position.unrealizedPnlPct >= 0 ? Color.green : Color.red)
                    }
                }
            }
        }
        .navigationTitle("Positions")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await model.refreshPositions()
        }
        .task(id: model.serverURLString) {
            await model.poll(every: 5) {
                await model.refreshPositions()
            }
        }
    }
}
