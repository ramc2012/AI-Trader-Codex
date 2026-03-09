import SwiftUI

struct AgentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ScreenBackdrop {
            HeroHeader(
                eyebrow: "Automation",
                title: "AI Agent",
                subtitle: "Observe runtime state, kill-switch status, strategy toggles, and the latest event stream."
            )

            if let error = model.agentError {
                EmptyPanel(title: "Agent Unavailable", message: error)
            }

            if let status = model.agentStatus {
                GlassCard {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Runtime Status")
                                    .font(.headline)
                                HStack(spacing: 8) {
                                    StatusCapsule(text: status.state.uppercased(), color: status.state.lowercased() == "running" ? .green : .orange)
                                    if status.emergencyStop == true {
                                        StatusCapsule(text: "Kill Switch", color: .red)
                                    }
                                }
                            }
                            Spacer()
                            if model.isRefreshingAgent {
                                ProgressView()
                            }
                        }

                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                            MetricTile(label: "Cycle", value: String(status.currentCycle), accent: .teal)
                            MetricTile(label: "Open Positions", value: String(status.positionsCount), accent: .indigo)
                            MetricTile(label: "Signals", value: String(status.totalSignals), accent: .orange)
                            MetricTile(label: "Trades", value: String(status.totalTrades), accent: .green)
                        }

                        HStack {
                            Text("Daily P&L")
                                .font(.subheadline.weight(.medium))
                            Spacer()
                            Text(DisplayFormatter.signedCurrency(status.dailyPnl))
                                .font(.title3.weight(.semibold))
                                .foregroundStyle(status.dailyPnl >= 0 ? Color.green : Color.red)
                        }

                        if let lastScanTime = status.lastScanTime {
                            Text("Last scan: \(DisplayFormatter.shortDateTime(lastScanTime))")
                                .font(.caption)
                                .foregroundStyle(Color.secondary)
                        }

                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 10) {
                                Button("Start Defaults") {
                                    Task { await model.startAgent() }
                                }
                                .buttonStyle(.borderedProminent)
                                .tint(.teal)

                                Button("Pause") {
                                    Task { await model.pauseAgent() }
                                }
                                .buttonStyle(.bordered)

                                Button("Resume") {
                                    Task { await model.resumeAgent() }
                                }
                                .buttonStyle(.bordered)

                                Button("Stop") {
                                    Task { await model.stopAgent() }
                                }
                                .buttonStyle(.bordered)
                                .tint(.red)
                            }
                        }

                        if let message = model.agentMessage {
                            Text(message)
                                .font(.subheadline)
                                .foregroundStyle(Color.teal)
                        }
                    }
                }
            }

            GlassCard {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Strategy Controls")
                        .font(.headline)

                    if model.strategyControls.isEmpty {
                        Text("Strategy controls are unavailable until the backend responds.")
                            .font(.subheadline)
                            .foregroundStyle(Color.secondary)
                    } else {
                        ForEach(model.strategyControls) { control in
                            Toggle(isOn: Binding(
                                get: { control.enabled },
                                set: { enabled in
                                    Task { await model.setStrategyEnabled(control.name, enabled: enabled) }
                                }
                            )) {
                                Text(control.name)
                                    .font(.subheadline.weight(.medium))
                            }
                            .tint(.teal)
                        }
                    }
                }
            }

            GlassCard {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Text("Recent Events")
                            .font(.headline)
                        Spacer()
                        Text("\(model.agentEvents.count) loaded")
                            .font(.caption)
                            .foregroundStyle(Color.secondary)
                    }

                    if model.agentEvents.isEmpty {
                        Text("No recent events yet.")
                            .font(.subheadline)
                            .foregroundStyle(Color.secondary)
                    }

                    ForEach(model.agentEvents.prefix(20)) { event in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(event.title)
                                    .font(.subheadline.weight(.semibold))
                                Spacer()
                                Text(event.severity.uppercased())
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(color(for: event.severity))
                            }
                            Text(event.message)
                                .font(.subheadline)
                            Text(DisplayFormatter.relativeDate(event.timestamp))
                                .font(.caption)
                                .foregroundStyle(Color.secondary)
                        }
                        .padding(.vertical, 6)
                    }
                }
            }
        }
        .navigationTitle("AI Agent")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await model.refreshAgent()
        }
        .task(id: model.serverURLString) {
            await model.poll(every: 5) {
                await model.refreshAgent()
            }
        }
    }

    private func color(for severity: String) -> Color {
        switch severity.lowercased() {
        case "success":
            return .green
        case "warning":
            return .orange
        case "error":
            return .red
        default:
            return .teal
        }
    }
}
