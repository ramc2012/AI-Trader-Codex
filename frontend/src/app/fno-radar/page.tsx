'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  ArrowRight,
  Compass,
  Loader2,
  Radar,
  RefreshCw,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { useATMWatchlist, type ATMOption } from '@/hooks/use-oi';
import { useRRGData } from '@/hooks/use-rrg';
import { formatDateTime, formatNumber } from '@/lib/formatters';
import { cn } from '@/lib/utils';

type Direction = -1 | 0 | 1;

interface TPOProfileSnapshot {
  poc: number;
  vah: number;
  val: number;
  ib_high: number;
  ib_low: number;
  open: number;
  close: number;
  high: number;
  low: number;
  total_volume: number;
}

interface RRGPointSnapshot {
  quadrant: string;
  rs_ratio: number;
  rs_momentum: number;
}

interface PillarAssessment {
  direction: Direction;
  strength: number;
  label: string;
  detail: string;
}

interface RadarRow {
  symbol: string;
  displayName: string;
  spot: number;
  atmStrike: number;
  straddlePct: number;
  pcr: number;
  setupScore: number;
  stance: 'Bullish Call' | 'Bearish Put' | 'Wait';
  confidence: 'High' | 'Medium' | 'Low';
  volatility: PillarAssessment;
  rotation: PillarAssessment;
  profile: PillarAssessment;
  oi: PillarAssessment;
  bullishTrigger: string;
  bearishTrigger: string;
  invalidation: string;
  note: string;
  profileSnapshot: TPOProfileSnapshot | null;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function formatPct(value: number, digits = 2): string {
  if (!Number.isFinite(value)) {
    return '--';
  }
  return `${value.toFixed(digits)}%`;
}

function getStanceTone(stance: RadarRow['stance']): string {
  if (stance === 'Bullish Call') {
    return 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20';
  }
  if (stance === 'Bearish Put') {
    return 'text-rose-300 bg-rose-500/10 border-rose-500/20';
  }
  return 'text-amber-200 bg-amber-500/10 border-amber-500/20';
}

function getConfidenceTone(confidence: RadarRow['confidence']): string {
  if (confidence === 'High') {
    return 'text-emerald-300';
  }
  if (confidence === 'Medium') {
    return 'text-amber-200';
  }
  return 'text-slate-300';
}

async function fetchProfileSnapshot(symbol: string): Promise<TPOProfileSnapshot | null> {
  const response = await fetch(`/api/v1/tpo/profile/${encodeURIComponent(symbol)}`);
  if (!response.ok) {
    return null;
  }

  const payload = await response.json();
  if (
    typeof payload?.poc !== 'number' ||
    typeof payload?.vah !== 'number' ||
    typeof payload?.val !== 'number'
  ) {
    return null;
  }

  return {
    poc: payload.poc,
    vah: payload.vah,
    val: payload.val,
    ib_high: payload.ib_high,
    ib_low: payload.ib_low,
    open: payload.open,
    close: payload.close,
    high: payload.high,
    low: payload.low,
    total_volume: payload.total_volume,
  };
}

function summarizeBreadth(
  data: { symbols?: Record<string, RRGPointSnapshot[]> } | undefined,
  label: string
): PillarAssessment {
  const latestPoints = Object.values(data?.symbols ?? {})
    .map((series) => series[series.length - 1])
    .filter(Boolean);

  if (latestPoints.length === 0) {
    return {
      direction: 0,
      strength: 8,
      label: 'No breadth read',
      detail: `${label} proxy unavailable in local history`,
    };
  }

  const counts = {
    Leading: 0,
    Improving: 0,
    Weakening: 0,
    Lagging: 0,
  };

  let score = 0;
  for (const point of latestPoints) {
    if (point.quadrant === 'Leading') {
      counts.Leading += 1;
      score += 1;
    } else if (point.quadrant === 'Improving') {
      counts.Improving += 1;
      score += 0.5;
    } else if (point.quadrant === 'Weakening') {
      counts.Weakening += 1;
      score -= 0.5;
    } else {
      counts.Lagging += 1;
      score -= 1;
    }
  }

  const normalizedScore = score / latestPoints.length;
  const direction: Direction =
    normalizedScore > 0.15 ? 1 : normalizedScore < -0.15 ? -1 : 0;
  const strength = clamp(Math.round(Math.abs(normalizedScore) * 25), 8, 25);

  const labelText =
    direction > 0
      ? 'Rotation supportive'
      : direction < 0
        ? 'Rotation fading'
        : 'Rotation mixed';

  return {
    direction,
    strength,
    label: labelText,
    detail: `${label}: ${counts.Leading} leading, ${counts.Improving} improving, ${counts.Weakening} weakening, ${counts.Lagging} lagging`,
  };
}

function buildVolatilityPillar(entry: ATMOption): PillarAssessment {
  const straddlePct = entry.spot > 0 ? (entry.straddle_price / entry.spot) * 100 : 0;
  const avgIv = (entry.ce_iv + entry.pe_iv) / 2;

  let strength = 8;
  let label = 'Premium heavy';

  if (straddlePct >= 0.8 && straddlePct <= 1.6) {
    strength = 25;
    label = 'Efficient premium';
  } else if (straddlePct >= 0.6 && straddlePct <= 2.2) {
    strength = 20;
    label = 'Tradable premium';
  } else if (straddlePct > 2.2 && straddlePct <= 3.0) {
    strength = 14;
    label = 'Premium expanding';
  }

  if (avgIv >= 10 && avgIv <= 25) {
    strength += 2;
  } else if (avgIv >= 35) {
    strength -= 2;
  }

  return {
    direction: 0,
    strength: clamp(strength, 4, 25),
    label,
    detail: `${formatPct(straddlePct)} straddle/spot, avg IV ${avgIv.toFixed(1)}`,
  };
}

function buildProfilePillar(
  entry: ATMOption,
  profile: TPOProfileSnapshot | null
): PillarAssessment {
  if (!profile) {
    return {
      direction: 0,
      strength: 8,
      label: 'Profile pending',
      detail: 'Local TPO profile unavailable for this symbol',
    };
  }

  const valueAreaWidth = Math.max(profile.vah - profile.val, entry.spot * 0.0025);
  const buffer = valueAreaWidth * 0.15;

  if (entry.spot >= profile.vah + buffer) {
    return {
      direction: 1,
      strength: 25,
      label: 'Accepted above value',
      detail: `Spot ${formatNumber(entry.spot, 0)} above VAH ${formatNumber(profile.vah, 0)}`,
    };
  }

  if (entry.spot > profile.poc + buffer * 0.25) {
    return {
      direction: 1,
      strength: 17,
      label: 'Holding upper value',
      detail: `POC ${formatNumber(profile.poc, 0)} is acting as support`,
    };
  }

  if (entry.spot <= profile.val - buffer) {
    return {
      direction: -1,
      strength: 25,
      label: 'Accepted below value',
      detail: `Spot ${formatNumber(entry.spot, 0)} below VAL ${formatNumber(profile.val, 0)}`,
    };
  }

  if (entry.spot < profile.poc - buffer * 0.25) {
    return {
      direction: -1,
      strength: 17,
      label: 'Holding lower value',
      detail: `POC ${formatNumber(profile.poc, 0)} is overhead resistance`,
    };
  }

  return {
    direction: 0,
    strength: 10,
    label: 'Inside value',
    detail: `Value area ${formatNumber(profile.val, 0)} to ${formatNumber(profile.vah, 0)}`,
  };
}

function buildOiPillar(entry: ATMOption): PillarAssessment {
  const pcr = entry.pcr;
  const oiSkew = (entry.pe_oi - entry.ce_oi) / Math.max(entry.ce_oi + entry.pe_oi, 1);

  if (pcr >= 1.15 && oiSkew > 0.08) {
    return {
      direction: 1,
      strength: 24,
      label: 'PE support dominant',
      detail: `PCR ${pcr.toFixed(2)} with PE OI ${formatNumber(entry.pe_oi)} over CE OI ${formatNumber(entry.ce_oi)}`,
    };
  }

  if (pcr >= 1.02 && oiSkew >= 0) {
    return {
      direction: 1,
      strength: 16,
      label: 'Put side supportive',
      detail: `PCR ${pcr.toFixed(2)} shows mild support`,
    };
  }

  if (pcr <= 0.85 && oiSkew < -0.08) {
    return {
      direction: -1,
      strength: 24,
      label: 'CE resistance dominant',
      detail: `PCR ${pcr.toFixed(2)} with CE OI ${formatNumber(entry.ce_oi)} over PE OI ${formatNumber(entry.pe_oi)}`,
    };
  }

  if (pcr < 0.98 && oiSkew <= 0) {
    return {
      direction: -1,
      strength: 16,
      label: 'Call side heavy',
      detail: `PCR ${pcr.toFixed(2)} shows overhead resistance`,
    };
  }

  return {
    direction: 0,
    strength: 10,
    label: 'Balanced OI',
    detail: `PCR ${pcr.toFixed(2)} is not directional yet`,
  };
}

function buildRotationPillar(
  symbol: string,
  niftyBreadth: PillarAssessment,
  bankingBreadth: PillarAssessment
): PillarAssessment {
  if (symbol === 'NSE:NIFTYBANK-INDEX') {
    return {
      ...bankingBreadth,
      detail: `${bankingBreadth.detail} · banking proxy`,
    };
  }

  if (symbol === 'NSE:FINNIFTY-INDEX') {
    return {
      ...bankingBreadth,
      strength: clamp(bankingBreadth.strength - 2, 6, 25),
      detail: `${bankingBreadth.detail} · FINNIFTY uses banking breadth proxy`,
    };
  }

  if (symbol === 'NSE:NIFTYMIDCAP50-INDEX') {
    return {
      ...niftyBreadth,
      strength: clamp(niftyBreadth.strength - 2, 6, 25),
      detail: `${niftyBreadth.detail} · MIDCPNIFTY uses NIFTY breadth proxy`,
    };
  }

  return {
    ...niftyBreadth,
    detail: `${niftyBreadth.detail} · NIFTY breadth proxy`,
  };
}

function buildRadarRow(
  entry: ATMOption,
  profile: TPOProfileSnapshot | null,
  niftyBreadth: PillarAssessment,
  bankingBreadth: PillarAssessment
): RadarRow {
  const volatility = buildVolatilityPillar(entry);
  const rotation = buildRotationPillar(entry.symbol, niftyBreadth, bankingBreadth);
  const profilePillar = buildProfilePillar(entry, profile);
  const oi = buildOiPillar(entry);

  const directionalStrength =
    rotation.strength + profilePillar.strength + oi.strength;
  const directionalBias =
    rotation.direction * rotation.strength +
    profilePillar.direction * profilePillar.strength +
    oi.direction * oi.strength;
  const alignment =
    directionalStrength > 0
      ? Math.abs(directionalBias) / directionalStrength
      : 0;

  const setupScore = clamp(
    Math.round(
      volatility.strength +
      directionalStrength * (0.45 + alignment * 0.55)
    ),
    0,
    100
  );

  const stance: RadarRow['stance'] =
    directionalBias >= 18
      ? 'Bullish Call'
      : directionalBias <= -18
        ? 'Bearish Put'
        : 'Wait';

  const confidence: RadarRow['confidence'] =
    setupScore >= 75 && alignment >= 0.7
      ? 'High'
      : setupScore >= 60
        ? 'Medium'
        : 'Low';

  const bullishTrigger = profile
    ? `Acceptance above VAH ${formatNumber(profile.vah, 0)}`
    : 'Wait for value acceptance above VAH';
  const bearishTrigger = profile
    ? `Acceptance below VAL ${formatNumber(profile.val, 0)}`
    : 'Wait for value acceptance below VAL';
  const invalidation = profile
    ? `Reject back into ${formatNumber(profile.val, 0)}-${formatNumber(profile.vah, 0)} value area`
    : 'Skip until local profile data is available';

  let note = 'Stay flat while profile and OI are not aligned.';
  if (stance === 'Bullish Call') {
    note = 'Prefer ATM or one-step ITM CE only while upper value hold and put support stay aligned.';
  } else if (stance === 'Bearish Put') {
    note = 'Prefer ATM or one-step ITM PE only while lower value hold and call resistance stay aligned.';
  }

  return {
    symbol: entry.symbol,
    displayName: entry.display_name,
    spot: entry.spot,
    atmStrike: entry.atm_strike,
    straddlePct: entry.spot > 0 ? (entry.straddle_price / entry.spot) * 100 : 0,
    pcr: entry.pcr,
    setupScore,
    stance,
    confidence,
    volatility,
    rotation,
    profile: profilePillar,
    oi,
    bullishTrigger,
    bearishTrigger,
    invalidation,
    note,
    profileSnapshot: profile,
  };
}

function SummaryCard({
  title,
  value,
  subtitle,
  icon: Icon,
}: {
  title: string;
  value: string;
  subtitle: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{title}</p>
        <Icon className="h-4 w-4 text-slate-500" />
      </div>
      <p className="mt-3 text-2xl font-semibold text-slate-100">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{subtitle}</p>
    </div>
  );
}

function PillarBar({
  title,
  pillar,
}: {
  title: string;
  pillar: PillarAssessment;
}) {
  const tone =
    pillar.direction > 0
      ? 'bg-emerald-500'
      : pillar.direction < 0
        ? 'bg-rose-500'
        : 'bg-amber-400';

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-200">{title}</p>
          <p className="mt-0.5 text-xs text-slate-400">{pillar.label}</p>
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold text-slate-100">{pillar.strength}/25</p>
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-800">
        <div
          className={cn('h-full rounded-full transition-all', tone)}
          style={{ width: `${(pillar.strength / 25) * 100}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-slate-500">{pillar.detail}</p>
    </div>
  );
}

export default function FnORadarPage() {
  const [selectedSymbol, setSelectedSymbol] = useState('');
  const { data: atmWatchlist, isLoading: atmLoading, isFetching: atmFetching } = useATMWatchlist();
  const niftyRRG = useRRGData('NIFTY50', '1D', 90);
  const bankingRRG = useRRGData('BANKING', '1D', 90);

  const entries = atmWatchlist?.entries ?? [];

  const profilesQuery = useQuery<Record<string, TPOProfileSnapshot | null>>({
    queryKey: ['fno-radar', 'profiles', entries.map((entry) => entry.symbol).join('|')],
    enabled: entries.length > 0,
    queryFn: async () => {
      const snapshots = await Promise.all(
        entries.map(async (entry) => [entry.symbol, await fetchProfileSnapshot(entry.symbol)] as const)
      );
      return Object.fromEntries(snapshots);
    },
    refetchInterval: 60_000,
  });

  const niftyBreadth = summarizeBreadth(niftyRRG.data, 'NIFTY50');
  const bankingBreadth = summarizeBreadth(bankingRRG.data, 'BANKING');

  const radarRows = entries
    .map((entry) =>
      buildRadarRow(
        entry,
        profilesQuery.data?.[entry.symbol] ?? null,
        niftyBreadth,
        bankingBreadth
      )
    )
    .sort((left, right) => right.setupScore - left.setupScore);

  const selectedRow =
    radarRows.find((row) => row.symbol === selectedSymbol) ?? radarRows[0] ?? null;

  const bullishCount = radarRows.filter((row) => row.stance === 'Bullish Call').length;
  const bearishCount = radarRows.filter((row) => row.stance === 'Bearish Put').length;
  const waitCount = radarRows.filter((row) => row.stance === 'Wait').length;
  const topScore = radarRows[0]?.setupScore ?? 0;
  const pageFetching =
    atmFetching || niftyRRG.isFetching || bankingRRG.isFetching || profilesQuery.isFetching;

  if (atmLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 px-5 py-4 text-sm text-slate-300">
          <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
          Building local FnO radar from option-chain and profile data...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[28px] border border-slate-800 bg-[radial-gradient(circle_at_top_left,_rgba(34,211,238,0.12),_transparent_30%),linear-gradient(135deg,rgba(15,23,42,0.95),rgba(2,6,23,0.98))] p-6 shadow-[0_20px_80px_rgba(2,6,23,0.45)]">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.24em] text-cyan-200">
              <Radar className="h-3.5 w-3.5" />
              Local Only
            </div>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-100">
              FnO Radar
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
              Swing-trade board for ATM index options. It combines premium efficiency,
              rotation breadth, market profile acceptance, and OI pressure into one
              local composite score so the plan is visible in the running instance.
            </p>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-right">
            <div className="flex items-center justify-end gap-2 text-xs text-slate-400">
              {pageFetching ? (
                <RefreshCw className="h-3.5 w-3.5 animate-spin text-cyan-300" />
              ) : (
                <Activity className="h-3.5 w-3.5 text-cyan-300" />
              )}
              Live local snapshot
            </div>
            <p className="mt-1 text-sm font-medium text-slate-100">
              {atmWatchlist?.timestamp ? formatDateTime(atmWatchlist.timestamp) : 'Waiting for market data'}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              No cloud dependency. Data is read from the local instance only.
            </p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <SummaryCard
            title="Live Setups"
            value={String(radarRows.length)}
            subtitle="Indices with ATM chain data in the local feed"
            icon={Compass}
          />
          <SummaryCard
            title="Bullish"
            value={String(bullishCount)}
            subtitle="Call-side setups with aligned breadth, profile, and OI"
            icon={TrendingUp}
          />
          <SummaryCard
            title="Bearish"
            value={String(bearishCount)}
            subtitle="Put-side setups with aligned breadth, profile, and OI"
            icon={TrendingDown}
          />
          <SummaryCard
            title="Top Score"
            value={`${topScore}/100`}
            subtitle={`${waitCount} setups are still in wait mode`}
            icon={ShieldCheck}
          />
        </div>
      </section>

      {radarRows.length === 0 ? (
        <section className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/60 p-8 text-center">
          <p className="text-sm font-medium text-slate-200">FnO radar has no local data yet.</p>
          <p className="mt-2 text-sm text-slate-400">
            Populate the option-chain snapshot locally, then reopen this page.
          </p>
        </section>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[1.45fr_0.95fr]">
          <section className="rounded-2xl border border-slate-800 bg-slate-900/70">
            <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">Radar Board</h2>
                <p className="mt-1 text-xs text-slate-400">
                  Ranked by composite alignment across volatility, breadth, profile, and OI.
                </p>
              </div>
              <div className="text-right text-xs text-slate-500">
                <p>NIFTY proxy: {niftyBreadth.label}</p>
                <p>BANKING proxy: {bankingBreadth.label}</p>
              </div>
            </div>

            <div className="overflow-x-auto">
              <div className="min-w-[860px]">
                <div className="grid grid-cols-[1.2fr_0.9fr_0.7fr_0.65fr_0.65fr_1fr_1fr] gap-3 border-b border-slate-800 px-5 py-3 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                  <span>Underlying</span>
                  <span>Plan</span>
                  <span className="text-right">Score</span>
                  <span className="text-right">Straddle</span>
                  <span className="text-right">PCR</span>
                  <span>Rotation</span>
                  <span>Profile</span>
                </div>

                {radarRows.map((row) => {
                  const active = row.symbol === selectedRow?.symbol;
                  return (
                    <button
                      key={row.symbol}
                      type="button"
                      onClick={() => setSelectedSymbol(row.symbol)}
                      className={cn(
                        'grid w-full grid-cols-[1.2fr_0.9fr_0.7fr_0.65fr_0.65fr_1fr_1fr] gap-3 border-b border-slate-800/70 px-5 py-4 text-left transition-colors',
                        active
                          ? 'bg-cyan-500/8'
                          : 'hover:bg-slate-800/40'
                      )}
                    >
                      <div>
                        <p className="text-sm font-semibold text-slate-100">{row.displayName}</p>
                        <p className="mt-1 text-xs text-slate-400">
                          Spot {formatNumber(row.spot, 0)} · ATM {formatNumber(row.atmStrike, 0)}
                        </p>
                      </div>
                      <div className="flex items-start">
                        <span className={cn('rounded-full border px-2.5 py-1 text-xs font-medium', getStanceTone(row.stance))}>
                          {row.stance}
                        </span>
                      </div>
                      <div className="text-right">
                        <p className="text-xl font-semibold text-slate-100">{row.setupScore}</p>
                        <p className={cn('mt-1 text-xs', getConfidenceTone(row.confidence))}>
                          {row.confidence}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-medium text-slate-100">{formatPct(row.straddlePct)}</p>
                        <p className="mt-1 text-xs text-slate-500">{row.volatility.label}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-medium text-slate-100">{row.pcr.toFixed(2)}</p>
                        <p className="mt-1 text-xs text-slate-500">{row.oi.label}</p>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-slate-100">{row.rotation.label}</p>
                        <p className="mt-1 text-xs text-slate-500">{row.rotation.strength}/25</p>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-slate-100">{row.profile.label}</p>
                        <p className="mt-1 text-xs text-slate-500">{row.profile.strength}/25</p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </section>

          {selectedRow && (
            <aside className="space-y-4">
              <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                      Selected Setup
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold text-slate-100">
                      {selectedRow.displayName}
                    </h2>
                    <p className="mt-1 text-sm text-slate-400">
                      Spot {formatNumber(selectedRow.spot, 0)} · ATM {formatNumber(selectedRow.atmStrike, 0)}
                    </p>
                  </div>
                  <div className="text-right">
                    <span className={cn('inline-flex rounded-full border px-3 py-1 text-sm font-medium', getStanceTone(selectedRow.stance))}>
                      {selectedRow.stance}
                    </span>
                    <p className="mt-2 text-3xl font-semibold text-slate-100">{selectedRow.setupScore}</p>
                    <p className={cn('text-sm', getConfidenceTone(selectedRow.confidence))}>
                      {selectedRow.confidence} confidence
                    </p>
                  </div>
                </div>

                <div className="mt-5 grid gap-3">
                  <PillarBar title="Volatility" pillar={selectedRow.volatility} />
                  <PillarBar title="Rotation" pillar={selectedRow.rotation} />
                  <PillarBar title="Profile" pillar={selectedRow.profile} />
                  <PillarBar title="OI Pressure" pillar={selectedRow.oi} />
                </div>
              </section>

              <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
                <h3 className="text-lg font-semibold text-slate-100">Execution Map</h3>
                <p className="mt-1 text-sm text-slate-400">
                  Local plan only. Use it as a checklist before opening the chain.
                </p>

                <div className="mt-4 space-y-3">
                  <div className="rounded-xl border border-emerald-500/15 bg-emerald-500/5 p-3">
                    <p className="text-xs uppercase tracking-[0.18em] text-emerald-300">Bullish trigger</p>
                    <p className="mt-1 text-sm text-slate-100">{selectedRow.bullishTrigger}</p>
                  </div>
                  <div className="rounded-xl border border-rose-500/15 bg-rose-500/5 p-3">
                    <p className="text-xs uppercase tracking-[0.18em] text-rose-300">Bearish trigger</p>
                    <p className="mt-1 text-sm text-slate-100">{selectedRow.bearishTrigger}</p>
                  </div>
                  <div className="rounded-xl border border-amber-500/15 bg-amber-500/5 p-3">
                    <p className="text-xs uppercase tracking-[0.18em] text-amber-200">Invalidation</p>
                    <p className="mt-1 text-sm text-slate-100">{selectedRow.invalidation}</p>
                  </div>
                </div>

                <p className="mt-4 text-sm leading-6 text-slate-300">{selectedRow.note}</p>

                {selectedRow.profileSnapshot && (
                  <div className="mt-4 grid grid-cols-2 gap-3 rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">POC</p>
                      <p className="mt-1 text-sm font-medium text-slate-100">
                        {formatNumber(selectedRow.profileSnapshot.poc, 0)}
                      </p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Value Area</p>
                      <p className="mt-1 text-sm font-medium text-slate-100">
                        {formatNumber(selectedRow.profileSnapshot.val, 0)} - {formatNumber(selectedRow.profileSnapshot.vah, 0)}
                      </p>
                    </div>
                  </div>
                )}
              </section>

              <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
                <h3 className="text-lg font-semibold text-slate-100">Drill Down</h3>
                <div className="mt-4 space-y-2">
                  <Link
                    href={`/indices/${encodeURIComponent(selectedRow.displayName.toLowerCase())}/options`}
                    className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-200 transition-colors hover:border-cyan-500/30 hover:text-cyan-200"
                  >
                    Open full option chain
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                  <Link
                    href={`/analytics?tab=profile&symbol=${encodeURIComponent(selectedRow.symbol)}`}
                    className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-200 transition-colors hover:border-cyan-500/30 hover:text-cyan-200"
                  >
                    Open market profile workspace
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </div>
              </section>
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
