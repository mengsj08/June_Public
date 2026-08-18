import { useEffect, useRef, useState } from 'react';
import { loadSystemAlerts, type SystemAlertsPayload } from '../services/canvasApi';

export default function SystemAlertBadge() {
  const [alerts, setAlerts] = useState<SystemAlertsPayload | null>(null);
  const [open, setOpen] = useState(false);
  const shellRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      void loadSystemAlerts().then((payload) => {
        if (!cancelled) setAlerts(payload);
      }).catch(() => {
        if (!cancelled) setAlerts(null);
      });
    };
    refresh();
    const interval = window.setInterval(refresh, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !shellRef.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  if (!alerts?.has_anomaly || alerts.count < 1 || alerts.items.length < 1) return null;

  return (
    <div className="system-alert-shell" ref={shellRef}>
      <button
        type="button"
        ref={triggerRef}
        className="system-alert-badge"
        aria-label={`${alerts.summary}，查看详情`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? 'system-alert-popover' : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true" className="system-alert-dot" />
        系统 {alerts.count}
      </button>
      {open && <section className="system-alert-popover" id="system-alert-popover" role="dialog" aria-label="系统异常">
        <header>
          <strong>系统异常</strong>
          <span>{alerts.count} 条</span>
        </header>
        <ul>
          {alerts.items.map((item) => <li key={item.key}>
            <span>{item.label}</span>
            <p>{item.message}</p>
          </li>)}
        </ul>
        <a href="/?view=console" target="_top">去调度台查看 <span aria-hidden="true">→</span></a>
      </section>}
    </div>
  );
}
