// 跳回任务卡看板。生产态 Studio 由看板后端同源托管在 /canvas/ 下,回根路径即回看板;
// vite dev 独立端口时回退到 /api 代理的同一目标(vite.config.ts proxy)。
const DEV_BOARD_URL = 'http://localhost:8890/';

// eslint-disable-next-line react-refresh/only-export-components -- exercised independently by host-link contract tests.
export function boardHref(): string {
  return window.location.pathname.startsWith('/canvas') ? '/' : DEV_BOARD_URL;
}

export default function BoardLink({ className = 'board-link' }: { className?: string }) {
  return (
    <a className={className} href={boardHref()} title="回到任务卡看板">
      ← 看板
    </a>
  );
}
