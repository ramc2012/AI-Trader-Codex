'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { ArrowRightLeft, ExternalLink, Loader2, RefreshCw } from 'lucide-react';

import CandlestickChart from '@/components/charts/candlestick-chart';
import { useCanonicalOptionChain, useOptionChart, useStraddleChart } from '@/hooks/use-options';
import { useGlobalContinuousWatchlist, useWatchlistUniverse } from '@/hooks/use-watchlist';
import {
  buildInstrumentOptions,
  defaultSymbolForMarket,
  filterInstrumentOptions,
} from '@/lib/instrument-universe';
import { cn } from '@/lib/utils';

const MARKET_FILTERS = ['ALL', 'NSE', 'BSE', 'US', 'CRYPTO'] as const;
const INDEX_OPTION_ROUTES: Record<string, string> = {
  'NSE:NIFTY50-INDEX': '/indices/nifty/options',
  'NSE:NIFTYBANK-INDEX': '/indices/banknifty/options',
  'NSE:FINNIFTY-INDEX': '/indices/finnifty/options',
  'NSE:NIFTYMIDCAP50-INDEX': '/indices/midcpnifty/options',
  'BSE:SENSEX-INDEX': '/indices/sensex/options',
};
const CHART_INTERVALS = ['5', '15', '30', '60'] as const;
const CHART_DAYS = [1, 3, 5, 10] as const;

type OptionChartTab = 'CE' | 'PE' | 'STRADDLE';

function formatUSD(value: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value);
}

function ActionLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
    >
      {label}
      <ExternalLink className="h-3.5 w-3.5" />
    </Link>
  );
}

export default function OptionsLandingPage() {
  const { data: universe, isLoading: universeLoading } = useWatchlistUniverse();
  const { data: globalWatch, isFetching: globalFetching } = useGlobalContinuousWatchlist(true);
  const options = useMemo(() => buildInstrumentOptions(universe), [universe]);
  const [market, setMarket] = useState<string>('ALL');
  const filteredOptions = useMemo(() => filterInstrumentOptions(options, market), [market, options]);
  const [requestedSymbol, setRequestedSymbol] = useState(() =>
    defaultSymbolForMarket(options, 'ALL', 'NSE:NIFTY50-INDEX'),
  );
  const symbol = useMemo(() => {
    if (filteredOptions.some((item) => item.value === requestedSymbol)) {
      return requestedSymbol;
    }
    return defaultSymbolForMarket(options, market, requestedSymbol);
  }, [filteredOptions, market, options, requestedSymbol]);

  const selected = useMemo(
    () => options.find((item) => item.value === symbol) ?? filteredOptions[0] ?? null,
    [filteredOptions, options, symbol],
  );
  const usTicker = selected?.value.split(':')[1]?.toUpperCase() ?? '';
  const usOptionFocus = useMemo(
    () => globalWatch?.us_options?.find((item) => item.symbol.toUpperCase() === usTicker) ?? null,
    [globalWatch?.us_options, usTicker],
  );
  const [requestedExpiryTs, setRequestedExpiryTs] = useState<number | null>(null);
  const [requestedStrike, setRequestedStrike] = useState<number | null>(null);
  const [chartTab, setChartTab] = useState<OptionChartTab>('STRADDLE');
  const [chartInterval, setChartInterval] = useState<(typeof CHART_INTERVALS)[number]>('15');
  const [chartDays, setChartDays] = useState<(typeof CHART_DAYS)[number]>(5);
  const supportsChain = Boolean(selected && selected.derivatives.includes('options') && !INDEX_OPTION_ROUTES[selected.value]);
  const chainQuery = useCanonicalOptionChain(
    selected?.value ?? '',
    requestedExpiryTs,
    14,
    3,
    supportsChain,
  );
  const expiryBlocks = useMemo(
    () => chainQuery.data?.data?.expiryData ?? [],
    [chainQuery.data?.data?.expiryData],
  );
  const activeExpiry = useMemo(
    () => expiryBlocks.find((block) => block.expiry_ts === requestedExpiryTs) ?? expiryBlocks[0] ?? null,
    [expiryBlocks, requestedExpiryTs],
  );
  const selectedStrike = useMemo(() => {
    if (!activeExpiry?.strikes.length) return null;
    if (requestedStrike !== null && activeExpiry.strikes.some((row) => row.strike === requestedStrike)) {
      return requestedStrike;
    }
    return [...activeExpiry.strikes].sort(
      (a, b) => Math.abs(a.strike - activeExpiry.spot) - Math.abs(b.strike - activeExpiry.spot),
    )[0]?.strike ?? activeExpiry.strikes[0]?.strike ?? null;
  }, [activeExpiry, requestedStrike]);
  const selectedRow = useMemo(
    () => activeExpiry?.strikes.find((row) => row.strike === selectedStrike) ?? activeExpiry?.strikes[0] ?? null,
    [activeExpiry, selectedStrike],
  );
  const ceChartQuery = useOptionChart(
    selectedRow?.ce.symbol,
    chartInterval,
    chartDays,
    Boolean(supportsChain && selectedRow?.ce.symbol),
  );
  const peChartQuery = useOptionChart(
    selectedRow?.pe.symbol,
    chartInterval,
    chartDays,
    Boolean(supportsChain && selectedRow?.pe.symbol),
  );
  const straddleQuery = useStraddleChart(
    selected?.value ?? '',
    activeExpiry?.expiry_ts ?? null,
    selectedRow?.strike ?? null,
    chartInterval,
    chartDays,
    Boolean(supportsChain && selected?.value && activeExpiry && selectedRow),
  );
  const currentChart = useMemo(() => {
    if (chartTab === 'CE') return ceChartQuery.data?.candles ?? [];
    if (chartTab === 'PE') return peChartQuery.data?.candles ?? [];
    return straddleQuery.data?.candles ?? [];
  }, [ceChartQuery.data?.candles, chartTab, peChartQuery.data?.candles, straddleQuery.data?.candles]);
  const activeChartError = chartTab === 'CE'
    ? ceChartQuery.error
    : chartTab === 'PE'
      ? peChartQuery.error
      : straddleQuery.error;
  const chartCandles = useMemo(
    () => currentChart
      .map((candle) => ({
        time: Math.floor(new Date(candle.timestamp).getTime() / 1000),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
        volume: candle.volume,
      }))
      .filter((candle) => Number.isFinite(candle.time)),
    [currentChart],
  );
  const chartLoading = (
    (chartTab === 'CE' && ceChartQuery.isLoading && chartCandles.length === 0)
    || (chartTab === 'PE' && peChartQuery.isLoading && chartCandles.length === 0)
    || (chartTab === 'STRADDLE' && straddleQuery.isLoading && chartCandles.length === 0)
  );
  const straddleFallbackStrike = (
    chartTab === 'STRADDLE'
    && selectedRow
    && straddleQuery.data?.strike
    && Math.abs(straddleQuery.data.strike - selectedRow.strike) > 0.001
  ) ? straddleQuery.data.strike : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-slate-100">Options Workspace</h2>
          <p className="mt-1 text-sm text-slate-400">
            Unified derivatives landing across the full watchlist universe
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          {(universeLoading || globalFetching) ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : null}
          <span>{globalWatch?.timestamp ? `Updated ${new Date(globalWatch.timestamp).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })} IST` : 'Using cached universe'}</span>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={market}
            onChange={(e) => {
              setMarket(e.target.value);
              setRequestedExpiryTs(null);
              setRequestedStrike(null);
            }}
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
          >
            {MARKET_FILTERS.map((item) => (
              <option key={item} value={item}>
                {item === 'ALL' ? 'All Markets' : item}
              </option>
            ))}
          </select>
          <select
            value={symbol}
            onChange={(e) => {
              setRequestedSymbol(e.target.value);
              setRequestedExpiryTs(null);
              setRequestedStrike(null);
            }}
            className="min-w-[260px] rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
          >
            {filteredOptions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          {selected ? (
            <span className="rounded-full bg-slate-800 px-3 py-1 text-xs text-slate-400">
              {selected.assetClass} · {selected.derivatives.length ? selected.derivatives.join(', ') : 'spot only'}
            </span>
          ) : null}
        </div>
      </div>

      {selected ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr,0.8fr]">
          <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-slate-100">{selected.label}</h3>
                <p className="mt-1 text-xs text-slate-500">{selected.value}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {INDEX_OPTION_ROUTES[selected.value] ? (
                  <ActionLink href={INDEX_OPTION_ROUTES[selected.value]} label="Open full index chain" />
                ) : null}
                <ActionLink href={`/analytics?tab=profile&symbol=${encodeURIComponent(selected.value)}`} label="Market profile" />
                <ActionLink href={`/analytics?tab=orderflow&symbol=${encodeURIComponent(selected.value)}`} label="Order flow" />
                <ActionLink href={`/analytics?tab=charts&symbol=${encodeURIComponent(selected.value)}`} label="Charts" />
              </div>
            </div>

            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4">
              {INDEX_OPTION_ROUTES[selected.value] ? (
                <div className="space-y-2 text-sm text-slate-300">
                  <div className="font-semibold text-emerald-300">Dedicated index options workspace available</div>
                  <p>
                    This instrument has a full option-chain workspace with chain, charts, analytics, and strategy builder.
                  </p>
                </div>
              ) : chainQuery.isLoading || chainQuery.isFetching ? (
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Loading option chain...
                </div>
              ) : activeExpiry ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-200">Live option chain</div>
                      <div className="text-xs text-slate-500">
                        Spot {activeExpiry.spot.toFixed(2)} · PCR {activeExpiry.pcr.toFixed(2)} · {activeExpiry.strikes.length} strikes
                      </div>
                    </div>
                    {expiryBlocks.length > 1 ? (
                      <select
                        value={String(activeExpiry.expiry_ts)}
                        onChange={(e) => {
                          setRequestedExpiryTs(Number(e.target.value));
                          setRequestedStrike(null);
                        }}
                        className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
                      >
                        {expiryBlocks.map((block) => (
                          <option key={block.expiry_ts} value={block.expiry_ts}>
                            {block.expiry_label}
                          </option>
                        ))}
                      </select>
                    ) : null}
                  </div>
                  <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                    <MetricTile label="Expiry" value={activeExpiry.expiry_label} tone="text-slate-100" />
                    <MetricTile label="Call OI" value={activeExpiry.total_call_oi.toLocaleString('en-IN')} tone="text-emerald-300" />
                    <MetricTile label="Put OI" value={activeExpiry.total_put_oi.toLocaleString('en-IN')} tone="text-rose-300" />
                    <MetricTile label="Integrity" value={`${activeExpiry.quality.integrity_score.toFixed(0)}%`} tone="text-sky-300" />
                  </div>
                  <div className="overflow-x-auto rounded-lg border border-slate-800">
                    <table className="w-full min-w-[820px] text-sm">
                      <thead>
                        <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wide text-slate-500">
                          <th className="px-3 py-2">Call LTP</th>
                          <th className="px-3 py-2">Call OI</th>
                          <th className="px-3 py-2 text-center">Strike</th>
                          <th className="px-3 py-2 text-right">Put OI</th>
                          <th className="px-3 py-2 text-right">Put LTP</th>
                        </tr>
                      </thead>
                      <tbody>
                        {activeExpiry.strikes.map((row) => (
                          <tr
                            key={`${activeExpiry.expiry}-${row.strike}`}
                            className={cn(
                              'cursor-pointer border-b border-slate-800/70 text-slate-300 transition-colors hover:bg-slate-900/70',
                              selectedRow?.strike === row.strike && 'bg-emerald-500/10',
                            )}
                            onClick={() => setRequestedStrike(row.strike)}
                          >
                            <td className="px-3 py-2 text-emerald-300">{row.ce.ltp.toFixed(4)}</td>
                            <td className="px-3 py-2">{row.ce.oi.toLocaleString('en-IN')}</td>
                            <td className="px-3 py-2 text-center font-semibold text-slate-100">{row.strike.toFixed(2)}</td>
                            <td className="px-3 py-2 text-right">{row.pe.oi.toLocaleString('en-IN')}</td>
                            <td className="px-3 py-2 text-right text-rose-300">{row.pe.ltp.toFixed(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {selectedRow ? (
                    <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-200">Contract history</div>
                          <div className="text-xs text-slate-500">
                            CE, PE, and ATM straddle candles for the selected expiry and strike
                          </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="flex rounded-lg border border-slate-700 bg-slate-950 p-1">
                            {(['CE', 'PE', 'STRADDLE'] as OptionChartTab[]).map((tab) => (
                              <button
                                key={tab}
                                onClick={() => setChartTab(tab)}
                                className={cn(
                                  'rounded-md px-3 py-1.5 text-xs font-medium',
                                  chartTab === tab
                                    ? 'bg-sky-500/15 text-sky-300'
                                    : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200',
                                )}
                              >
                                {tab === 'STRADDLE' ? 'ATM Straddle' : tab}
                              </button>
                            ))}
                          </div>
                          <select
                            value={String(selectedRow.strike)}
                            onChange={(e) => setRequestedStrike(Number(e.target.value))}
                            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
                          >
                            {activeExpiry.strikes.map((row) => (
                              <option key={`strike-${row.strike}`} value={row.strike}>
                                Strike {row.strike.toFixed(2)}
                              </option>
                            ))}
                          </select>
                          <select
                            value={chartInterval}
                            onChange={(e) => setChartInterval(e.target.value as (typeof CHART_INTERVALS)[number])}
                            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500"
                          >
                            {CHART_INTERVALS.map((item) => (
                              <option key={item} value={item}>{item}m</option>
                            ))}
                          </select>
                        </div>
                      </div>
                      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr,280px]">
                        <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3">
                          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <div className="text-xs uppercase tracking-wide text-slate-500">
                                {chartTab === 'STRADDLE' ? 'ATM Straddle' : `${chartTab} contract`} · {chartInterval}m · {chartDays}D
                              </div>
                              {straddleFallbackStrike ? (
                                <div className="mt-1 text-[11px] text-amber-300">
                                  Using nearest strike with chart data: {straddleFallbackStrike.toFixed(2)}
                                </div>
                              ) : null}
                            </div>
                            <div className="flex items-center gap-1">
                              {CHART_DAYS.map((item) => (
                                <button
                                  key={item}
                                  onClick={() => setChartDays(item)}
                                  className={cn(
                                    'rounded-md border px-2 py-1 text-xs',
                                    chartDays === item
                                      ? 'border-sky-500 bg-sky-500/10 text-sky-300'
                                      : 'border-slate-700 text-slate-400 hover:bg-slate-900',
                                  )}
                                >
                                  {item === 1 ? '1D' : `${item}D`}
                                </button>
                              ))}
                            </div>
                          </div>
                          {chartLoading ? (
                            <div className="flex h-[360px] items-center justify-center text-sm text-slate-400">
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                              Loading contract chart...
                            </div>
                          ) : activeChartError ? (
                            <div className="flex h-[360px] items-center justify-center text-center text-sm text-amber-300">
                              {activeChartError instanceof Error
                                ? activeChartError.message
                                : 'Option chart unavailable for the selected contract.'}
                            </div>
                          ) : chartCandles.length > 0 ? (
                            <CandlestickChart data={chartCandles} height={360} lockViewport />
                          ) : (
                            <div className="flex h-[360px] items-center justify-center text-sm text-slate-500">
                              No chart candles available for the selected contract.
                            </div>
                          )}
                        </div>
                        <div className="space-y-3">
                          <MetricTile label="Strike" value={selectedRow.strike.toFixed(2)} tone="text-slate-100" />
                          <MetricTile label="Call" value={formatUSD(selectedRow.ce.ltp)} tone="text-emerald-300" />
                          <MetricTile label="Put" value={formatUSD(selectedRow.pe.ltp)} tone="text-rose-300" />
                          <MetricTile label="Straddle" value={formatUSD(selectedRow.ce.ltp + selectedRow.pe.ltp)} tone="text-sky-300" />
                          <ContractInfo label="CE Symbol" value={selectedRow.ce.symbol} tone="text-emerald-300" />
                          <ContractInfo label="PE Symbol" value={selectedRow.pe.symbol} tone="text-rose-300" />
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : usOptionFocus ? (
                <div className="space-y-3">
                  <div className="text-sm font-semibold text-slate-200">US ATM option snapshot</div>
                  <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                    <MetricTile label="Spot" value={formatUSD(usOptionFocus.spot ?? 0)} tone="text-slate-100" />
                    <MetricTile label="ATM Strike" value={usOptionFocus.atm_strike ? usOptionFocus.atm_strike.toFixed(2) : '—'} tone="text-sky-300" />
                    <MetricTile label="Call" value={usOptionFocus.call_last ? formatUSD(usOptionFocus.call_last) : '—'} tone="text-emerald-300" />
                    <MetricTile label="Put" value={usOptionFocus.put_last ? formatUSD(usOptionFocus.put_last) : '—'} tone="text-rose-300" />
                  </div>
                  <p className="text-xs text-slate-500">
                    Expiry {usOptionFocus.expiry ?? '—'} · bid/ask snapshot from the global watchlist feed.
                  </p>
                </div>
              ) : chainQuery.isError ? (
                <div className="space-y-2 text-sm text-slate-300">
                  <div className="font-semibold text-amber-300">Option chain unavailable</div>
                  <p>
                    {chainQuery.error instanceof Error
                      ? chainQuery.error.message
                      : `No option chain available for ${selected.value}.`}
                  </p>
                </div>
              ) : (
                <div className="space-y-2 text-sm text-slate-300">
                  <div className="font-semibold text-amber-300">No dedicated options chain page yet</div>
                  <p>
                    This instrument is part of the unified watchlist and analytics universe. Use Charts, Market Profile, and Order Flow from the links above.
                  </p>
                </div>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
            <div className="mb-3 flex items-center gap-2">
              <ArrowRightLeft className="h-4 w-4 text-sky-400" />
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Universe Coverage</h3>
            </div>
            <div className="space-y-3 text-sm text-slate-400">
              <p>Indian indices route into the full options chain workspace.</p>
              <p>US underlyings now stream a live public chain via Nasdaq and stay selectable across analytics.</p>
              <p>Crypto options are available for BTC and ETH via Deribit. Other crypto pairs remain spot-only.</p>
            </div>
          </div>
        </div>
      ) : null}

      <div className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-slate-200">Watchlist Universe</div>
            <div className="text-[11px] text-slate-500">All instruments currently available across options and analytics</div>
          </div>
          <div className="text-xs text-slate-500">{filteredOptions.length} instrument(s)</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Instrument</th>
                <th className="px-4 py-3">Market</th>
                <th className="px-4 py-3">Asset</th>
                <th className="px-4 py-3">Derivatives</th>
                <th className="px-4 py-3 text-right">Workspace</th>
              </tr>
            </thead>
            <tbody>
              {filteredOptions.map((item) => {
                const indexRoute = INDEX_OPTION_ROUTES[item.value];
                const availableUsFocus = globalWatch?.us_options?.some((row) => row.symbol.toUpperCase() === item.value.split(':')[1]?.toUpperCase());
                return (
                  <tr key={item.value} className={cn('border-b border-slate-800/70 text-slate-300', item.value === symbol && 'bg-emerald-500/5')}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-100">{item.label}</div>
                      <div className="text-xs text-slate-500">{item.value}</div>
                    </td>
                    <td className="px-4 py-3">{item.market}</td>
                    <td className="px-4 py-3 capitalize">{item.assetClass.replace('_', ' ')}</td>
                    <td className="px-4 py-3">{item.derivatives.length ? item.derivatives.join(', ') : 'spot'}</td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex flex-wrap justify-end gap-2">
                        {indexRoute ? <ActionLink href={indexRoute} label="Index chain" /> : null}
                        {availableUsFocus ? <span className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-sky-300">Live chain</span> : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function MetricTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={cn('mt-1 text-lg font-semibold', tone)}>{value}</div>
    </div>
  );
}

function ContractInfo({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={cn('mt-1 truncate text-sm font-medium', tone)}>{value || '—'}</div>
    </div>
  );
}
