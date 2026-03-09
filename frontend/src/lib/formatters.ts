/**
 * Format a number as INR currency using Indian number system (lakhs/crores).
 */
export function formatINR(value: number): string {
  const absValue = Math.abs(value);
  const sign = value < 0 ? '-' : '';

  if (absValue >= 1_00_00_000) {
    const crores = absValue / 1_00_00_000;
    return `${sign}\u20B9${crores.toFixed(2)} Cr`;
  }
  if (absValue >= 1_00_000) {
    const lakhs = absValue / 1_00_000;
    return `${sign}\u20B9${lakhs.toFixed(2)} L`;
  }

  return `${sign}\u20B9${absValue.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * Format a number as INR with full precision (no abbreviation).
 */
export function formatINRFull(value: number): string {
  const sign = value < 0 ? '-' : '';
  const absValue = Math.abs(value);
  return `${sign}\u20B9${absValue.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * Format number in selected currency (INR/USD currently).
 */
export function formatCurrency(value: number, currency: string = 'INR'): string {
  const code = (currency || 'INR').toUpperCase();
  const locale = code === 'USD' ? 'en-US' : 'en-IN';
  const sign = value < 0 ? '-' : '';
  const absValue = Math.abs(value);
  return `${sign}${absValue.toLocaleString(locale, {
    style: 'currency',
    currency: code === 'USD' ? 'USD' : 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * Format a number as a percentage.
 */
export function formatPercent(value: number, decimals = 2): string {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(decimals)}%`;
}

/**
 * Format a plain number with commas (Indian system).
 */
export function formatNumber(value: number, decimals = 0): string {
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Format an ISO date string to IST date.
 */
export function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

/**
 * Format an ISO date string to IST time (HH:MM:SS).
 */
export function formatTime(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/**
 * Format an ISO date string to IST date + time.
 */
export function formatDateTime(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/**
 * Get current IST time as a formatted string.
 */
export function getCurrentIST(): string {
  return new Date().toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}
