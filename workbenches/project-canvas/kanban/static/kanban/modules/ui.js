function camelizeId(id) {
  return String(id).replace(/-([a-z0-9])/g, (_, ch) => ch.toUpperCase());
}

export function setupUi(ctx) {
  const domIds = [
    'login-overlay', 'login-step-quiz', 'login-step-user', 'quiz-toast', 'quiz-countdown-hero',
    'quiz-question', 'quiz-options', 'quiz-name', 'quiz-error', 'quiz-submit', 'quiz-countdown',
    'login-user-close', 'login-members',
    'btn-logout', 'btn-settings', 'hdr-username', 'hdr-summary', 'hdr-audience-label', 'stats', 'tabs', 'views',
    'sw-mine', 'sw-done', 'chk-mine', 'chk-done',
    'sync-indicator', 'sync-label', 'sync-pop-line-1', 'sync-pop-line-2', 'sync-pop-line-3',
    'btn-new-project', 'btn-search', 'btn-queue', 'queue-badge', 'btn-overflow', 'hdr-overflow-menu',
    'overflow-settings', 'overflow-switch-user', 'overflow-logout', 'overflow-filter-mine',
    'overflow-filter-done', 'overflow-chk-mine', 'overflow-chk-done', 'overflow-clock',
    'overflow-btn-audience',
    'sw-sync-git', 'chk-sync-git', 'sync-track-git', 'sync-switch-label-git',
    'overflow-sw-sync-git', 'overflow-chk-sync-git',
    'modal-new', 'new-project', 'proj-dropdown', 'new-project-err', 'new-body', 'ai-title-cb',
    'title-input-wrap', 'new-title', 'new-assignee', 'new-priority', 'new-due-date',
    'btn-cancel', 'btn-create', 'btn-ai-split', 'btn-ai-create', 'btn-ai-arrow', 'ai-tool-dd',
    'modal-settings', 'settings-user', 'settings-claude', 'settings-codex',
    'btn-settings-cancel', 'btn-settings-save',
    'toast', 'task-toast-stack',
    'queue-overlay', 'queue-sidebar', 'queue-close-btn', 'processed-badge', 'running-count',
    'queued-count', 'queue-tab-processed', 'queue-tab-running', 'queue-tab-queued',
    'detail-overlay', 'detail-back-btn', 'detail-title', 'detail-edit-btn', 'detail-claude-btn',
    'detail-codex-btn', 'detail-copy-btn', 'detail-queue-btn', 'detail-queue-badge',
    'detail-status-bar', 'detail-loading', 'detail-error', 'detail-body-area', 'detail-md-content',
    'detail-view-mode', 'detail-edit-mode', 'detail-editor',
    'editor-save-btn', 'editor-cancel-btn', 'editor-status', 'ai-activity', 'ai-activity-list',
    'detail-sidebar', 'detail-sidebar-toggle', 'detail-sidebar-info-tab', 'detail-sidebar-comments-tab',
    'detail-sidebar-comments-badge', 'detail-sidebar-fold-btn', 'detail-sidebar-info',
    'detail-sidebar-comments', 'detail-props', 'detail-file-path',
    'lightbox-overlay', 'lightbox-image', 'lightbox-caption',
    'file-mention-dd', 'fm-tabs', 'fm-results',
  ];

  const dom = {};
  domIds.forEach((id) => {
    dom[camelizeId(id)] = document.getElementById(id);
  });

  const STATUS = ['todo', 'in-progress', 'review', 'done'];
  const SL = {'todo': '待办', 'in-progress': '进行中', 'review': '评审中', 'done': '已完成'};
  const PL = {'high': '高', 'medium': '中', 'low': '低'};
  const PRIORITIES = ['high', 'medium', 'low'];
  const FLATPICKR_LOCALE = window.flatpickr && flatpickr.l10ns && flatpickr.l10ns.zh ? flatpickr.l10ns.zh : 'zh';

  function isMobile() {
    return window.matchMedia('(max-width:768px)').matches;
  }

  function dueDateText(dueDate, status) {
    if (!dueDate || status === 'done') return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const due = new Date(dueDate + 'T00:00:00');
    if (Number.isNaN(due.getTime())) return null;
    due.setHours(0, 0, 0, 0);
    const diff = Math.round((due - today) / 86400000);
    if (diff > 0) return { text: '还剩' + diff + '天', overdue: false };
    if (diff === 0) return { text: '今天到期', overdue: false };
    return { text: '逾期' + Math.abs(diff) + '天', overdue: true };
  }

  function esc(s) {
    if (!s) return '';
    const span = document.createElement('span');
    span.textContent = s;
    return span.innerHTML;
  }

  function badge(cls, txt) {
    return '<span class="b ' + cls + '">' + esc(txt) + '</span>';
  }

  function toast(msg, isErr) {
    const el = dom.toast;
    if (!el) return;
    el.textContent = msg;
    el.className = 'toast' + (isErr ? ' err' : '');
    requestAnimationFrame(() => el.classList.add('on'));
    clearTimeout(ctx.uiState.timers.toast);
    ctx.uiState.timers.toast = setTimeout(() => el.classList.remove('on'), 2500);
  }

  function closeAllDd() {
    document.querySelectorAll('.dd.on').forEach((dd) => {
      dd.classList.remove('on');
      if (dd.parentElement) dd.parentElement.classList.remove('open');
    });
  }

  function makeDd(items, current, onSelect) {
    const wrap = document.createElement('span');
    wrap.className = 'dd-wrap';

    const trigger = document.createElement('span');
    trigger.className = 'b b-' + current;
    trigger.textContent = items[current] || current;

    const dd = document.createElement('div');
    dd.className = 'dd';

    Object.entries(items).forEach(([key, value]) => {
      const item = document.createElement('div');
      item.className = 'dd-item';
      const badgeEl = document.createElement('span');
      badgeEl.className = 'b b-' + key;
      badgeEl.textContent = value;
      item.appendChild(badgeEl);
      item.onclick = (event) => {
        event.stopPropagation();
        closeAllDd();
        onSelect(key);
      };
      dd.appendChild(item);
    });

    trigger.onclick = (event) => {
      event.stopPropagation();
      closeAllDd();
      dd.classList.toggle('on');
      wrap.classList.toggle('open', dd.classList.contains('on'));
    };

    wrap.appendChild(trigger);
    wrap.appendChild(dd);
    return wrap;
  }

  function makeMemberDd(current, members, onSelect) {
    const wrap = document.createElement('span');
    wrap.className = 'dd-wrap';

    const trigger = document.createElement('span');
    trigger.className = 'b b-who';
    trigger.textContent = current || '未分配';

    const dd = document.createElement('div');
    dd.className = 'dd';

    members.forEach((member) => {
      const item = document.createElement('div');
      item.className = 'dd-item';
      const badgeEl = document.createElement('span');
      badgeEl.className = 'b b-who';
      badgeEl.textContent = member;
      item.appendChild(badgeEl);
      item.onclick = (event) => {
        event.stopPropagation();
        closeAllDd();
        onSelect(member);
      };
      dd.appendChild(item);
    });

    trigger.onclick = (event) => {
      event.stopPropagation();
      closeAllDd();
      dd.classList.toggle('on');
      wrap.classList.toggle('open', dd.classList.contains('on'));
    };

    wrap.appendChild(trigger);
    wrap.appendChild(dd);
    return wrap;
  }

  document.addEventListener('click', closeAllDd);

  ctx.el = dom;
  ctx.ui = {
    STATUS,
    SL,
    PL,
    PRIORITIES,
    FLATPICKR_LOCALE,
    dom,
    isMobile,
    dueDateText,
    esc,
    badge,
    toast,
    closeAllDd,
    makeDd,
    makeMemberDd,
  };

  return ctx.ui;
}
