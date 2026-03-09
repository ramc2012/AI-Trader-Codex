'use client';

import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import { ECHARTS_DARK_THEME } from '@/lib/echarts-theme';

interface EChartsWrapperProps {
  option: echarts.EChartsOption;
  height?: string;
  className?: string;
  onInit?: (chart: echarts.ECharts) => void;
}

export function EChartsWrapper({ option, height = '400px', className = '', onInit }: EChartsWrapperProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current, undefined, { renderer: 'canvas' });
      onInit?.(chartRef.current);
    }

    // Merge dark theme defaults
    const mergedOption = {
      ...ECHARTS_DARK_THEME,
      ...option,
      backgroundColor: 'transparent',
    };
    chartRef.current.setOption(mergedOption, true);

    const handleResize = () => chartRef.current?.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, [option, onInit]);

  useEffect(() => {
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  return <div ref={containerRef} style={{ height, width: '100%' }} className={className} />;
}
