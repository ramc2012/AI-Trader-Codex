'use client';

import { useMemo } from 'react';
import { EChartsWrapper } from '@/components/charts/EChartsWrapper';
import { CHART_COLORS } from '@/lib/echarts-theme';
import type { EChartsOption } from 'echarts';

interface OIChartProps {
  strikes: number[];
  ceOI: number[];
  peOI: number[];
  atmStrike?: number;
  height?: string;
}

/**
 * ECharts bar chart showing CE OI (green, pointing up) and PE OI (red, pointing down)
 * at each strike price. The ATM strike is highlighted with a vertical mark line.
 */
export function OIChart({ strikes, ceOI, peOI, atmStrike, height = '400px' }: OIChartProps) {
  const option: EChartsOption = useMemo(() => {
    const markLineData = atmStrike
      ? [
          {
            xAxis: String(atmStrike),
            label: {
              formatter: `ATM ${atmStrike}`,
              color: CHART_COLORS.accent4,
              fontSize: 10,
              position: 'end' as const,
            },
            lineStyle: {
              color: CHART_COLORS.accent4,
              type: 'dashed' as const,
              width: 1.5,
            },
          },
        ]
      : [];

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: unknown) => {
          const items = params as Array<{
            name: string;
            seriesName: string;
            value: number;
            color: string;
          }>;
          if (!items || items.length === 0) return '';
          const strike = items[0].name;
          let html = `<div style="font-size:12px;font-weight:600;margin-bottom:4px;">Strike: ${strike}</div>`;
          for (const item of items) {
            const val = Math.abs(item.value);
            const label = item.seriesName;
            html += `<div style="display:flex;align-items:center;gap:6px;font-size:11px;margin-top:2px;">
              <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${item.color}"></span>
              <span>${label}: ${val.toLocaleString('en-IN')}</span>
            </div>`;
          }
          return html;
        },
      },
      legend: {
        data: ['CE OI', 'PE OI'],
        top: 8,
        textStyle: { color: CHART_COLORS.textSecondary, fontSize: 11 },
      },
      grid: {
        left: 60,
        right: 30,
        top: 50,
        bottom: 40,
      },
      xAxis: {
        type: 'category',
        data: strikes.map(String),
        axisLabel: {
          color: CHART_COLORS.textMuted,
          fontSize: 10,
          rotate: strikes.length > 20 ? 45 : 0,
        },
        axisLine: { lineStyle: { color: CHART_COLORS.axisLine } },
        axisTick: { lineStyle: { color: CHART_COLORS.axisLine } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: CHART_COLORS.textMuted,
          fontSize: 10,
          formatter: (val: number) => {
            const abs = Math.abs(val);
            if (abs >= 1_00_00_000) return `${(val / 1_00_00_000).toFixed(1)}Cr`;
            if (abs >= 1_00_000) return `${(val / 1_00_000).toFixed(1)}L`;
            if (abs >= 1_000) return `${(val / 1_000).toFixed(0)}K`;
            return String(val);
          },
        },
        splitLine: {
          lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' },
        },
        axisLine: { lineStyle: { color: CHART_COLORS.axisLine } },
      },
      series: [
        {
          name: 'CE OI',
          type: 'bar',
          data: ceOI,
          itemStyle: {
            color: CHART_COLORS.ceColor,
            borderRadius: [3, 3, 0, 0],
          },
          emphasis: {
            itemStyle: { color: '#4ade80' },
          },
          markLine:
            markLineData.length > 0
              ? { data: markLineData, silent: true, symbol: 'none' }
              : undefined,
        },
        {
          name: 'PE OI',
          type: 'bar',
          // PE OI rendered downward (negative values)
          data: peOI.map((v) => -v),
          itemStyle: {
            color: CHART_COLORS.peColor,
            borderRadius: [0, 0, 3, 3],
          },
          emphasis: {
            itemStyle: { color: '#f87171' },
          },
        },
      ],
    };
  }, [strikes, ceOI, peOI, atmStrike]);

  if (strikes.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 text-sm text-slate-500"
        style={{ height }}
      >
        No OI data available
      </div>
    );
  }

  return <EChartsWrapper option={option} height={height} />;
}

export default OIChart;
