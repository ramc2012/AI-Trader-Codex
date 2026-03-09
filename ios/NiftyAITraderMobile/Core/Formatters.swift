import Foundation

enum DisplayFormatter {
    private static let signedNumberFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        return formatter
    }()

    private static let compactFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 1
        formatter.usesSignificantDigits = false
        return formatter
    }()

    private static let relativeFormatter = RelativeDateTimeFormatter()

    static func currency(_ value: Double, code: String = "INR") -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = code
        formatter.maximumFractionDigits = 2
        formatter.locale = Locale(identifier: code == "INR" ? "en_IN" : "en_US")
        return formatter.string(from: NSNumber(value: value)) ?? String(format: "%.2f", value)
    }

    static func signedCurrency(_ value: Double, code: String = "INR") -> String {
        let prefix = value >= 0 ? "+" : "-"
        return prefix + currency(abs(value), code: code)
    }

    static func percent(_ value: Double) -> String {
        String(format: "%+.2f%%", value)
    }

    static func number(_ value: Double) -> String {
        signedNumberFormatter.string(from: NSNumber(value: value)) ?? String(format: "%.2f", value)
    }

    static func compact(_ value: Double) -> String {
        let absolute = abs(value)
        let divisor: Double
        let suffix: String

        switch absolute {
        case 1_000_000_000...:
            divisor = 1_000_000_000
            suffix = "B"
        case 1_000_000...:
            divisor = 1_000_000
            suffix = "M"
        case 1_000...:
            divisor = 1_000
            suffix = "K"
        default:
            divisor = 1
            suffix = ""
        }

        let formatted = compactFormatter.string(from: NSNumber(value: value / divisor)) ?? String(format: "%.1f", value / divisor)
        return formatted + suffix
    }

    static func shortDateTime(_ isoString: String?) -> String {
        guard let isoString, let date = parsedDate(from: isoString) else {
            return "Unavailable"
        }
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    static func relativeDate(_ isoString: String?) -> String {
        guard let isoString, let date = parsedDate(from: isoString) else {
            return "Unavailable"
        }
        return relativeFormatter.localizedString(for: date, relativeTo: Date())
    }

    private static func parsedDate(from isoString: String) -> Date? {
        ISO8601DateFormatter.full.date(from: isoString) ?? ISO8601DateFormatter.basic.date(from: isoString)
    }
}

private extension ISO8601DateFormatter {
    static let full: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    static let basic: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()
}
