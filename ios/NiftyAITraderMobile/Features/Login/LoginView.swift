import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var model: AppModel
    @State private var safariSession: SafariSession?

    var body: some View {
        ScreenBackdrop {
            HeroHeader(
                eyebrow: "Connectivity",
                title: "Fyers Login",
                subtitle: "Use the phone to start the real Fyers OAuth flow, then complete auth by submitting the redirect URL or auth code back to the backend."
            )

            GlassCard {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Backend")
                        .font(.headline)
                    TextField("http://127.0.0.1:8000", text: $model.serverURLString)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .padding(12)
                        .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    Text("Use your Mac's LAN IP for a physical device. The app automatically appends `/api/v1`.")
                        .font(.footnote)
                        .foregroundStyle(Color.secondary)
                }
            }

            GlassCard {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Text("Connection State")
                            .font(.headline)
                        Spacer()
                        if model.isRefreshingAuth {
                            ProgressView()
                        }
                    }

                    HStack(spacing: 10) {
                        StatusCapsule(
                            text: model.authStatus?.authenticated == true ? "Authenticated" : "Signed Out",
                            color: model.authStatus?.authenticated == true ? .green : .orange
                        )
                        StatusCapsule(
                            text: model.authStatus?.appConfigured == true ? "App Configured" : "App Missing Keys",
                            color: model.authStatus?.appConfigured == true ? .teal : .red
                        )
                        if model.tokenStatus?.refreshTokenValid == true {
                            StatusCapsule(text: "Refresh Ready", color: .indigo)
                        }
                    }

                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                        MetricTile(
                            label: "Access Token",
                            value: model.tokenStatus?.accessTokenValid == true ? "Valid" : "Expired",
                            accent: model.tokenStatus?.accessTokenValid == true ? .green : .orange
                        )
                        MetricTile(
                            label: "Refresh Window",
                            value: model.tokenStatus?.refreshTokenExpiresInDays.map { String(format: "%.1f days", $0) } ?? "Unknown",
                            accent: .indigo
                        )
                    }

                    if let authMessage = model.authMessage {
                        Text(authMessage)
                            .font(.subheadline)
                            .foregroundStyle(Color.teal)
                    }

                    if let authError = model.authError {
                        Text(authError)
                            .font(.subheadline)
                            .foregroundStyle(Color.red)
                    }
                }
            }

            GlassCard {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Fyers Credentials")
                        .font(.headline)

                    TextField("App ID", text: $model.credentialsDraft.appID)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(12)
                        .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 16, style: .continuous))

                    SecureField("Secret Key", text: $model.credentialsDraft.secretKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(12)
                        .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 16, style: .continuous))

                    TextField("Redirect URI", text: $model.credentialsDraft.redirectURI)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .padding(12)
                        .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 16, style: .continuous))

                    HStack {
                        Button("Save & Get Fyers Login") {
                            Task { await model.saveAndLogin() }
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.teal)
                        .disabled(model.isSubmittingAuthAction)

                        Button("Login with Fyers") {
                            Task { await model.openSavedLoginURL() }
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.isSubmittingAuthAction)
                    }

                    Text("`Login with Fyers` opens the broker OAuth page on the phone. After approval, paste the full redirect URL or the `auth_code` below.")
                        .font(.footnote)
                        .foregroundStyle(Color.secondary)
                }
            }

            GlassCard {
                VStack(alignment: .leading, spacing: 14) {
                    Text("OAuth Completion")
                        .font(.headline)

                    TextField("Paste full redirect URL or auth code", text: $model.authCode)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(12)
                        .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 16, style: .continuous))

                    Button("Submit to Backend") {
                        Task { await model.submitManualAuthCode() }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.indigo)
                    .disabled(model.authCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isSubmittingAuthAction)
                }
            }

            GlassCard {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Token Operations")
                        .font(.headline)

                    SecureField("6-digit PIN", text: $model.pin)
                        .keyboardType(.numberPad)
                        .padding(12)
                        .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 16, style: .continuous))

                    Toggle("Save PIN for automatic refresh", isOn: $model.savePinAfterRefresh)
                        .tint(.teal)

                    HStack {
                        Button("Auto Refresh") {
                            Task { await model.autoRefreshToken() }
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.orange)

                        Button("Refresh With PIN") {
                            Task { await model.refreshTokenWithPin() }
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.pin.count < 6 || model.isSubmittingAuthAction)
                    }

                    HStack {
                        Button("Save PIN") {
                            Task { await model.savePin() }
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.pin.count < 6 || model.isSubmittingAuthAction)

                        Button("Logout") {
                            Task { await model.logout() }
                        }
                        .buttonStyle(.bordered)
                        .tint(.red)
                        .disabled(model.isSubmittingAuthAction)
                    }
                }
            }
        }
        .navigationTitle("Login")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await model.refreshAuth()
        }
        .task(id: model.serverURLString) {
            await model.refreshAuth()
        }
        .onChange(of: model.pendingLoginURL) { _, url in
            guard let url else { return }
            safariSession = SafariSession(url: url)
            model.consumePendingLoginURL()
        }
        .sheet(item: $safariSession) { session in
            SafariSheet(url: session.url)
                .ignoresSafeArea()
        }
    }
}

private struct SafariSession: Identifiable {
    let id = UUID()
    let url: URL
}
