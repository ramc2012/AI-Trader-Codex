'use client';

import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  Activity,
} from 'lucide-react';
import { useHealth } from '@/hooks/use-health';
import { useAlerts } from '@/hooks/use-alerts';
import { formatDateTime } from '@/lib/formatters';
import { cn } from '@/lib/utils';

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn('animate-pulse rounded bg-slate-800', className)} />
  );
}

function StatusIcon({ status }: { status: string }) {
  switch (status.toLowerCase()) {
    case 'healthy':
    case 'ok':
    case 'up':
      return <CheckCircle className="h-4 w-4 text-emerald-400" />;
    case 'degraded':
    case 'warning':
      return <AlertTriangle className="h-4 w-4 text-yellow-400" />;
    case 'unhealthy':
    case 'down':
    case 'error':
      return <XCircle className="h-4 w-4 text-red-400" />;
    default:
      return <Clock className="h-4 w-4 text-slate-400" />;
  }
}

function statusBadgeClass(status: string): string {
  switch (status.toLowerCase()) {
    case 'healthy':
    case 'ok':
    case 'up':
      return 'bg-emerald-500/20 text-emerald-400';
    case 'degraded':
    case 'warning':
      return 'bg-yellow-500/20 text-yellow-400';
    case 'unhealthy':
    case 'down':
    case 'error':
      return 'bg-red-500/20 text-red-400';
    default:
      return 'bg-slate-700 text-slate-400';
  }
}

function alertLevelBadgeClass(level: string): string {
  switch (level.toLowerCase()) {
    case 'info':
      return 'bg-blue-500/20 text-blue-400';
    case 'warning':
      return 'bg-yellow-500/20 text-yellow-400';
    case 'critical':
      return 'bg-orange-500/20 text-orange-400';
    case 'emergency':
      return 'bg-red-500/20 text-red-400';
    default:
      return 'bg-slate-700 text-slate-400';
  }
}

export default function MonitoringPage() {
  const { data: health, isLoading: healthLoading, error: healthError } = useHealth();
  const { data: alerts, isLoading: alertsLoading, error: alertsError } = useAlerts();

  const components = health?.components
    ? Object.entries(health.components)
    : [];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">
          Monitoring
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          System health and alert feed
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* System Health Panel */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-slate-400" />
              <h3 className="text-lg font-semibold text-slate-200">
                System Health
              </h3>
            </div>
            {health && (
              <span
                className={cn(
                  'rounded-full px-3 py-1 text-xs font-medium',
                  statusBadgeClass(health.overall_status)
                )}
              >
                {health.overall_status.toUpperCase()}
              </span>
            )}
          </div>

          {healthLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full rounded-lg" />
              ))}
            </div>
          ) : healthError ? (
            <p className="text-sm text-red-400">
              Failed to load health data. Backend may be offline.
            </p>
          ) : components.length === 0 ? (
            <p className="text-sm text-slate-500">No component data</p>
          ) : (
            <div className="space-y-2">
              {components.map(([key, comp]) => (
                <div
                  key={key}
                  className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-4 py-3"
                >
                  <div className="flex items-center gap-3">
                    <StatusIcon status={comp.status} />
                    <div>
                      <p className="text-sm font-medium text-slate-200">
                        {comp.name}
                      </p>
                      <p className="text-xs text-slate-500">{comp.message}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {comp.latency_ms !== null && (
                      <span className="text-xs text-slate-400">
                        {comp.latency_ms}ms
                      </span>
                    )}
                    <span
                      className={cn(
                        'rounded px-2 py-0.5 text-xs font-medium',
                        statusBadgeClass(comp.status)
                      )}
                    >
                      {comp.status.toUpperCase()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {health?.checked_at && (
            <p className="mt-3 text-xs text-slate-600">
              Last checked: {formatDateTime(health.checked_at)}
            </p>
          )}
        </div>

        {/* Alert Feed */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-4 flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-slate-400" />
            <h3 className="text-lg font-semibold text-slate-200">
              Alert Feed
            </h3>
          </div>

          {alertsLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-lg" />
              ))}
            </div>
          ) : alertsError ? (
            <p className="text-sm text-red-400">
              Failed to load alerts. Backend may be offline.
            </p>
          ) : !alerts || alerts.length === 0 ? (
            <div className="flex h-48 items-center justify-center">
              <p className="text-sm text-slate-500">No alerts</p>
            </div>
          ) : (
            <div className="max-h-[600px] space-y-2 overflow-y-auto">
              {alerts.map((alert) => (
                <div
                  key={alert.alert_id}
                  className={cn(
                    'rounded-lg border bg-slate-950 px-4 py-3',
                    alert.acknowledged
                      ? 'border-slate-800'
                      : 'border-slate-700'
                  )}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            'rounded px-2 py-0.5 text-xs font-medium',
                            alertLevelBadgeClass(alert.level)
                          )}
                        >
                          {alert.level.toUpperCase()}
                        </span>
                        <h4 className="text-sm font-medium text-slate-200">
                          {alert.title}
                        </h4>
                      </div>
                      <p className="mt-1 text-xs text-slate-400">
                        {alert.message}
                      </p>
                    </div>
                    {alert.acknowledged && (
                      <CheckCircle className="ml-2 h-4 w-4 shrink-0 text-slate-600" />
                    )}
                  </div>
                  <div className="mt-2 flex items-center gap-3 text-xs text-slate-600">
                    <span>{alert.source}</span>
                    <span>{formatDateTime(alert.timestamp)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
