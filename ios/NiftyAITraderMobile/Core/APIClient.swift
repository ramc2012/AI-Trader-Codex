import Foundation

enum APIClientError: LocalizedError {
    case invalidServerURL
    case invalidResponse
    case server(String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .invalidServerURL:
            return "Enter a valid backend URL, for example http://127.0.0.1:8000"
        case .invalidResponse:
            return "The backend returned an invalid response."
        case let .server(message):
            return message
        case let .decoding(message):
            return "Failed to decode backend response: \(message)"
        }
    }
}

private struct APIErrorEnvelope: Decodable {
    let detail: JSONValue?
    let message: String?
}

struct APIClient: Sendable {
    let baseURL: URL
    private let session: URLSession

    init(serverURLString: String) throws {
        let trimmed = serverURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalized = trimmed.hasSuffix("/api/v1")
            ? trimmed
            : trimmed.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/api/v1"

        guard let url = URL(string: normalized), let scheme = url.scheme, ["http", "https"].contains(scheme) else {
            throw APIClientError.invalidServerURL
        }

        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 30
        configuration.waitsForConnectivity = true

        self.baseURL = url
        self.session = URLSession(configuration: configuration)
    }

    func get<T: Decodable>(_ path: String) async throws -> T {
        try await request(path: path, method: "GET")
    }

    func post<T: Decodable, Body: Encodable>(_ path: String, body: Body) async throws -> T {
        try await request(path: path, method: "POST", body: body)
    }

    private func request<T: Decodable, Body: Encodable>(
        path: String,
        method: String,
        body: Body?
    ) async throws -> T {
        guard let url = URL(string: path.trimmingCharacters(in: CharacterSet(charactersIn: "/")), relativeTo: baseURL)?
            .absoluteURL else {
            throw APIClientError.invalidServerURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let body {
            request.httpBody = try Self.encoder.encode(body)
        }

        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIClientError.invalidResponse
        }

        guard (200 ... 299).contains(httpResponse.statusCode) else {
            let message = Self.serverMessage(from: data, statusCode: httpResponse.statusCode)
            throw APIClientError.server(message)
        }

        do {
            return try Self.decoder.decode(T.self, from: data)
        } catch {
            throw APIClientError.decoding(error.localizedDescription)
        }
    }

    private func request<T: Decodable>(
        path: String,
        method: String
    ) async throws -> T {
        guard let url = URL(string: path.trimmingCharacters(in: CharacterSet(charactersIn: "/")), relativeTo: baseURL)?
            .absoluteURL else {
            throw APIClientError.invalidServerURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIClientError.invalidResponse
        }

        guard (200 ... 299).contains(httpResponse.statusCode) else {
            let message = Self.serverMessage(from: data, statusCode: httpResponse.statusCode)
            throw APIClientError.server(message)
        }

        do {
            return try Self.decoder.decode(T.self, from: data)
        } catch {
            throw APIClientError.decoding(error.localizedDescription)
        }
    }

    private static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        return encoder
    }

    private static func serverMessage(from data: Data, statusCode: Int) -> String {
        if let decoded = try? decoder.decode(APIErrorEnvelope.self, from: data) {
            if let detail = decoded.detail?.displayText, !detail.isEmpty {
                return detail
            }
            if let message = decoded.message, !message.isEmpty {
                return message
            }
        }

        if let text = String(data: data, encoding: .utf8), !text.isEmpty {
            return "HTTP \(statusCode): \(text)"
        }

        return "HTTP \(statusCode)"
    }
}
