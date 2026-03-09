'use client';

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { EChartsWrapper } from './EChartsWrapper';
import { CHART_COLORS, SERIES_PALETTE } from '@/lib/echarts-theme';

interface RRGSymbolData {
  symbol: string;
  points: { rs_ratio: number; rs_momentum: number; timestamp: string }[];
}

interface RRGChartProps {
  data: Record<string, RRGSymbolData['points']>;
  height?: string;
}

export function RRGChart({ data, height = '500px' }: RRGChartProps) {
  const option = useMemo((): EChartsOption => {
    const symbols = Object.keys(data);

    const series = symbols.map((symbol, idx) => {
      const points = data[symbol];
      const color = SERIES_PALETTE[idx % SERIES_PALETTE.length];
      const lineData = points.map((p) => [p.rs_ratio, p.rs_momentum]);

      return [
        // Trail line
        {
          name: symbol,
          type: 'line' as const,
          data: lineData,
          smooth: true,
          lineStyle: { color, width: 2 },
          showSymbol: false,
          z: 2,
        },
        // Head marker (last point)
        {
          name: `${symbol}_head`,
          type: 'scatter' as const,
          data: lineData.length > 0 ? [lineData[lineData.length - 1]] : [],
          symbolSize: 10,
          itemStyle: { color },
          label: {
            show: true,
            formatter: symbol.replace('NSE:', '').replace('-EQ', ''),
            position: 'right' as const,
            color: CHART_COLORS.textPrimary,
            fontSize: 10,
          },
          z: 3,
        },
      ];
    }).flat();

    return {
      tooltip: {
        trigger: 'item',
        formatter: (params: any) => {
          if (!params.data) return '';
          return `${params.seriesName}<br/>RS-Ratio: ${params.data[0]}<br/>RS-Momentum: ${params.data[1]}`;
        },
      },
      legend: { show: false },
      xAxis: {
        name: 'RS-Ratio →',
        nameLocation: 'middle',
        nameGap: 30,
        min: 'dataMin',
        max: 'dataMax',
        splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' } },
      },
      yAxis: {
        name: 'RS-Momentum →',
        nameLocation: 'middle',
        nameGap: 40,
        min: 'dataMin',
        max: 'dataMax',
        splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'dashed' } },
      },
      // Quadrant markings
      markArea: {
        silent: true,
        data: [
          [{ xAxis: 100, yAxis: 100, itemStyle: { color: 'rgba(34,197,94,0.06)' } }, { xAxis: 'max', yAxis: 'max' }],
          [{ xAxis: 100, yAxis: 'min', itemStyle: { color: 'rgba(245,158,11,0.06)' } }, { xAxis: 'max', yAxis: 100 }],
          [{ xAxis: 'min', yAxis: 'min', itemStyle: { color: 'rgba(239,68,68,0.06)' } }, { xAxis: 100, yAxis: 100 }],
          [{ xAxis: 'min', yAxis: 100, itemStyle: { color: 'rgba(59,130,246,0.06)' } }, { xAxis: 100, yAxis: 'max' }],
        ],
      },
      series,
    };
  }, [data]);

  return <EChartsWrapper option={option} height={height} />;
}
