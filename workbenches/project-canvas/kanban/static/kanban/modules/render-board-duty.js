// KAN-1600: mounted by main.js; dependencies arrive through ctx.renderBoardInternal.
export function setupRenderBoardDuty(ctx) {
  const board = ctx.renderBoardInternal;
  if (!board) throw new Error("setupRenderBoard(ctx) must run first");
  const { dataState, uiState, SL, PL, dueDateText, makeDd, CONSOLE_AUDIENCE_OWNER, CONSOLE_AUDIENCE_ATTENTION_GATE } = board;
  const sortTasks = (...args) => board.sortTasks(...args);
  const getFilteredTasks = (...args) => board.getFilteredTasks(...args);
  const createCardEl = (...args) => board.createCardEl(...args);
  const updateTaskStatus = (...args) => board.updateTaskStatus(...args);
  const statusCount = (...args) => board.statusCount(...args);
  const consoleReviewCount = (...args) => board.consoleReviewCount(...args);
  const makeOverviewMetric = (...args) => board.makeOverviewMetric(...args);
  const makeOverviewSection = (...args) => board.makeOverviewSection(...args);
  const makeProgressSummary = (...args) => board.makeProgressSummary(...args);
  const makeCoordinationSummary = (...args) => board.makeCoordinationSummary(...args);
  const ensureAttentionGateDutyLoaded = (...args) => board.ensureAttentionGateDutyLoaded(...args);
  const consoleAudienceIsAttentionGate = (...args) => board.consoleAudienceIsAttentionGate(...args);
  const markConsoleAudience = (...args) => board.markConsoleAudience(...args);
  const openDutySource = (...args) => board.openDutySource(...args);
  const markDutySource = (...args) => board.markDutySource(...args);
  const makeDutySourceButton = (...args) => board.makeDutySourceButton(...args);
  const dutyShortStamp = (...args) => board.dutyShortStamp(...args);
  const dutyText = (...args) => board.dutyText(...args);
  const isDueNow = (...args) => board.isDueNow(...args);

  function makeDutyBlock(titleText, sourceRef) {
    const block = document.createElement('section');
    block.className = 'console-duty-block';
    markDutySource(block, sourceRef);
    const head = document.createElement('div');
    head.className = 'console-duty-block-head';
    const title = document.createElement('h4');
    title.textContent = titleText;
    head.appendChild(title);
    head.appendChild(makeDutySourceButton(sourceRef));
    block.appendChild(head);
    const body = document.createElement('div');
    body.className = 'console-duty-block-body';
    block.appendChild(body);
    return { block, body };
  }

  function makeDutyEmpty(text, sourceRef) {
    const empty = document.createElement('div');
    empty.className = 'console-duty-empty';
    empty.textContent = text;
    markDutySource(empty, sourceRef);
    return empty;
  }

  function dutyLines(text) {
    return String(text || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  }

  function dutyAssertLines(text, keys) {
    const wanted = Array.isArray(keys) ? new Set(keys) : null;
    return dutyLines(text).filter((line) => {
      const match = /^-\s*ASSERT\s+([^:]+):/.exec(line);
      return match && (!wanted || wanted.has(match[1]));
    });
  }

  function dutyFirstNumber(line, fallback = null) {
    const match = String(line || '').match(/(\d+)/);
    return match ? Number(match[1]) : fallback;
  }

  function dutyCount(lines, pattern) {
    return (Array.isArray(lines) ? lines : []).filter((line) => pattern.test(line)).length;
  }

  function dutyCountText(value) {
    return Number.isFinite(value) ? String(value) : '待核对';
  }

  function makeDutyOwnerStatement(text, evidence, sourceRef) {
    const details = document.createElement('details');
    details.className = 'console-duty-owner-statement';
    markDutySource(details, sourceRef);

    const summary = document.createElement('summary');
    const sentence = document.createElement('span');
    sentence.className = 'console-duty-owner-sentence';
    sentence.textContent = text;
    const check = document.createElement('span');
    check.className = 'console-duty-owner-check';
    check.textContent = '去核对';
    summary.appendChild(sentence);
    summary.appendChild(check);
    details.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'console-duty-owner-evidence';
    const lines = Array.isArray(evidence) && evidence.length ? evidence : ['暂无原始断言'];
    // 证据只展前 12 条撑核对,全量走源文件——防几十条原始断言把 Owner 面铺成日志
    const EVIDENCE_LINE_CAP = 12;
    lines.slice(0, EVIDENCE_LINE_CAP).forEach((line) => {
      const row = document.createElement('div');
      row.className = 'console-duty-owner-evidence-line';
      row.textContent = line && typeof line === 'object' ? dutyText(line.text) : line;
      markDutySource(row, (line && typeof line === 'object' && line.sourceRef) || sourceRef);
      body.appendChild(row);
    });
    if (lines.length > EVIDENCE_LINE_CAP) {
      const more = document.createElement('div');
      more.className = 'console-duty-owner-evidence-line';
      more.textContent = '… 其余 ' + (lines.length - EVIDENCE_LINE_CAP) + ' 条断言未展开，点右侧源文件看全量';
      markDutySource(more, sourceRef);
      body.appendChild(more);
    }
    body.appendChild(makeDutySourceButton(sourceRef));
    details.appendChild(body);
    return details;
  }

  function appendDutyOwnerStatements(body, statements, sourceRef) {
    const usable = (Array.isArray(statements) ? statements : []).filter((item) => item && item.text);
    if (!usable.length) {
      body.appendChild(makeDutyEmpty('暂无可展示断言', sourceRef));
      return;
    }
    usable.slice(0, 3).forEach((item) => {
      body.appendChild(makeDutyOwnerStatement(item.text, item.evidence, item.sourceRef || sourceRef));
    });
  }

  function weeklyDutyStatementModel(weekly) {
    const content = dutyText(weekly && weekly.content);
    const lines = dutyAssertLines(content);
    const find = (key) => lines.find((line) => line.includes('ASSERT ' + key + ':')) || '';
    const decisionLine = find('decision-log-count');
    const outboundLine = find('outbound-count');
    const newCardLine = find('new-card-count');
    const northStarScopeLine = find('north-star-explicit-scope-count');
    const unansweredLine = find('north-star-unanswered-count');
    const fsCountLine = find('fs-new-project-shaped-count');
    const fsDirLines = lines.filter((line) => line.includes('ASSERT fs-new-project-shaped-dir:'));
    const outboundEntryLines = lines.filter((line) => line.includes('ASSERT outbound-entry:'));
    const decisionCount = dutyFirstNumber(decisionLine);
    const outboundCount = dutyFirstNumber(outboundLine);
    const outboundPass = dutyCount(outboundEntryLines, /\bverdict=pass\b/);
    const outboundHit = dutyCount(outboundEntryLines, /\bverdict=hit\b/);
    const newCardCount = dutyFirstNumber(newCardLine);
    const northStarScopeCount = northStarScopeLine
      ? dutyFirstNumber(northStarScopeLine)
      : newCardCount;
    const unansweredCount = dutyFirstNumber(unansweredLine);
    const fsCount = dutyFirstNumber(fsCountLine);
    const fsUnlinked = dutyCount(fsDirLines, /\bkanban_card=no\b/);
    return [
      {
        text: (
          '本周决策账新增 ' + dutyCountText(decisionCount) + ' 条；外发闸记录 '
          + dutyCountText(outboundCount) + ' 条（pass ' + outboundPass + '、hit ' + outboundHit + '）。'
        ),
        evidence: [decisionLine, outboundLine].concat(outboundEntryLines).filter(Boolean),
      },
      {
        text: (
          '本周有 ' + dutyCountText(northStarScopeCount) + ' 张卡明确关联北极星，其中 '
          + dutyCountText(unansweredCount) + ' 张还没拿到「是否推进第一单」的回答。'
        ),
        evidence: [northStarScopeLine || newCardLine, unansweredLine].filter(Boolean),
      },
      {
        text: (
          '本周新出现项目形状目录 ' + dutyCountText(fsCount) + ' 个，其中 '
          + fsUnlinked + ' 个还没挂卡。'
        ),
        evidence: [fsCountLine].concat(fsDirLines).filter(Boolean),
      },
    ];
  }

  function renderDutyWeeklyOwner(container, weekly) {
    const sourceRef = weekly && weekly.source_ref;
    const { block, body } = makeDutyBlock('本周周报', sourceRef);
    if (weekly && weekly.exists && weekly.content) {
      const meta = document.createElement('div');
      meta.className = 'console-duty-meta';
      meta.textContent = [dutyText(weekly.week), dutyShortStamp(weekly.generated_at)].filter(Boolean).join(' · ');
      markDutySource(meta, sourceRef);
      if (meta.textContent) body.appendChild(meta);
      appendDutyOwnerStatements(body, weeklyDutyStatementModel(weekly), sourceRef);
    } else {
      body.appendChild(makeDutyEmpty(dutyText(weekly && weekly.empty_state, '周五晚生成'), sourceRef));
    }
    container.appendChild(block);
  }

  function renderDutyAutograntOwner(container, receipt) {
    const sourceRef = receipt && receipt.source_ref;
    const { block, body } = makeDutyBlock('代批回执', sourceRef);
    const count = Number(receipt && receipt.count) || 0;
    const range = [dutyText(receipt && receipt.week_start), dutyText(receipt && receipt.week_end)].filter(Boolean).join('..');
    const entries = Array.isArray(receipt && receipt.recent_entries) ? receipt.recent_entries : [];
    const evidence = entries.length ? entries.map((entry) => ({
      text: dutyText(entry && entry.line) || [
        dutyText(entry && entry.date),
        dutyText(entry && entry.task_id),
        dutyText(entry && entry.title),
      ].filter(Boolean).join(' · '),
      sourceRef: entry && entry.source_ref,
    })) : [
      range ? 'week: ' + range : '',
      'class:auto-人闸代批 count=' + count,
      dutyText(receipt && receipt.command),
    ].filter(Boolean);
    appendDutyOwnerStatements(body, [{
      text: '本周人闸代批 ' + count + ' 件。',
      evidence,
    }], sourceRef);
    container.appendChild(block);
  }

  function renderDutyOutboundOwner(container, ledger) {
    const sourceRef = ledger && ledger.source_ref;
    const { block, body } = makeDutyBlock('外发台账尾巴', sourceRef);
    const entries = Array.isArray(ledger && ledger.entries) ? ledger.entries : [];
    const count = Number(ledger && ledger.count) || 0;
    const latest = entries[entries.length - 1] || null;
    const verdictCounts = entries.reduce((acc, entry) => {
      const key = dutyText(entry && entry.verdict, 'unknown');
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
    const verdictText = Object.keys(verdictCounts).sort().map((key) => key + ' ' + verdictCounts[key]).join('、') || '无尾巴记录';
    const latestText = latest
      ? '最新一条是 ' + dutyText(latest.channel, 'general') + ' → ' + dutyText(latest.target, '未标目标') + '，verdict=' + dutyText(latest.verdict, 'unknown') + '。'
      : '当前没有可展示的外发尾巴记录。';
    const evidence = entries.map((entry) => ({
      text: [
        dutyShortStamp(entry.ts),
        'channel=' + dutyText(entry.channel, 'general'),
        'target=' + dutyText(entry.target, '未标目标'),
        'verdict=' + dutyText(entry.verdict, 'unknown'),
      ].join(' · '),
      sourceRef: entry && entry.source_ref,
    }));
    appendDutyOwnerStatements(body, [{
      text: '外发台账当前可读 ' + count + ' 条，值守页展示最近 ' + entries.length + ' 条（' + verdictText + '）。',
      evidence,
    }, {
      text: latestText,
      evidence: latest ? [evidence[evidence.length - 1]] : evidence,
      sourceRef: latest && latest.source_ref,
    }], sourceRef);
    container.appendChild(block);
  }

  function activeDutyStatusLabel(status) {
    const text = dutyText(status, 'unknown');
    if (/待追认|ai-draft/i.test(text)) return '待你追认';
    if (/owner-confirmed|confirmed|已确认/i.test(text)) return '已确认';
    return '未标状态';
  }

  function renderDutyActiveOwner(container, active) {
    const sourceRef = active && active.source_ref;
    const { block, body } = makeDutyBlock('活跃决策条', sourceRef);
    const entries = Array.isArray(active && active.entries) ? active.entries : [];
    const confirmed = entries.filter((entry) => activeDutyStatusLabel(entry.status) === '已确认');
    const pending = entries.filter((entry) => activeDutyStatusLabel(entry.status) === '待你追认');
    const unknown = entries.filter((entry) => activeDutyStatusLabel(entry.status) === '未标状态');
    const labelList = (items) => items.map((entry) => dutyText(entry.label, '未命名')).join('、') || '无';
    const evidenceFor = (items) => items.map((entry) => {
      const head = dutyText(entry.label, '未命名') + '|' + dutyText(entry.status, 'unknown');
      return {
        text: '- 【' + head + '】' + dutyText(entry.body),
        sourceRef: entry && entry.source_ref,
      };
    });
    const statements = [
      confirmed.length ? {
        text: '已确认的活跃边界有 ' + confirmed.length + ' 条：' + labelList(confirmed) + '。',
        evidence: evidenceFor(confirmed),
      } : null,
      pending.length ? {
        text: '待你追认的活跃草案有 ' + pending.length + ' 条：' + labelList(pending) + '。',
        evidence: evidenceFor(pending),
      } : null,
      unknown.length ? {
        text: '未标状态的活跃条目有 ' + unknown.length + ' 条：' + labelList(unknown) + '。',
        evidence: evidenceFor(unknown),
      } : null,
    ].filter(Boolean);
    appendDutyOwnerStatements(body, statements, sourceRef);
    container.appendChild(block);
  }

  // KAN-979 值守断言语法：周报 frontmatter 压成一行 meta；ASSERT 行 = 小标签 + 一句白话，
  // 长路径/数据源/命令折进证据层（hover 全量），不进第一屏正文。
  function weeklyFrontmatterMeta(content) {
    const parts = [];
    dutyLines(content).forEach((ln) => {
      if (!/^>/.test(ln)) return;
      ln.replace(/^>\s*/, '').split('·').forEach((seg) => {
        const s = seg.trim();
        let m;
        if ((m = /^doc_type:\s*(.+)$/i.exec(s))) parts.push(m[1].trim());
        else if ((m = /^generated_by:\s*(.+)$/i.exec(s))) parts.push(m[1].trim());
        else if (/^dry_run:\s*true$/i.test(s)) parts.push('dry-run');
        else if (/^no_llm:\s*true$/i.test(s)) parts.push('no-llm');
      });
    });
    return parts;
  }

  function splitDutyAssertEvidence(rest) {
    const markers = ['数据源:', '数据源：', '排除规则复用', '来源:', '来源：', 'source `', '；source', '; source'];
    let cut = -1;
    markers.forEach((mk) => {
      const i = rest.indexOf(mk);
      if (i >= 0 && (cut === -1 || i < cut)) cut = i;
    });
    if (cut === -1) {
      const p = rest.search(/\/Users\//);
      if (p >= 0) cut = p;
    }
    if (cut === -1) return { body: rest, evidence: '' };
    const body = rest.slice(0, cut).replace(/[；;、,\s]+$/, '').trim();
    const evidence = rest.slice(cut).trim();
    return { body: body || rest, evidence };
  }

  function parseDutyAssert(line) {
    const m = /^-\s*ASSERT\s+([^:：]+)[:：]\s*([\s\S]*)$/.exec(String(line || '').trim());
    if (!m) return null;
    const { body, evidence } = splitDutyAssertEvidence(m[2].trim());
    return { key: m[1].trim(), body, evidence };
  }

  function makeDutyAssertion(assert, sourceRef) {
    const hasEvidence = Boolean(assert.evidence);
    const wrap = document.createElement(hasEvidence ? 'details' : 'div');
    wrap.className = 'console-duty-assert';
    markDutySource(wrap, sourceRef);
    const head = document.createElement(hasEvidence ? 'summary' : 'div');
    head.className = 'console-duty-assert-head';
    const tag = document.createElement('span');
    tag.className = 'console-duty-assert-tag';
    tag.textContent = assert.key;
    const text = document.createElement('span');
    text.className = 'console-duty-assert-body';
    text.textContent = assert.body;
    head.appendChild(tag);
    head.appendChild(text);
    if (hasEvidence) {
      const more = document.createElement('span');
      more.className = 'console-duty-assert-more';
      more.textContent = '源';
      head.appendChild(more);
    }
    wrap.appendChild(head);
    if (hasEvidence) {
      const ev = document.createElement('div');
      ev.className = 'console-duty-assert-evidence';
      ev.textContent = assert.evidence;
      markDutySource(ev, sourceRef);
      wrap.appendChild(ev);
    }
    return wrap;
  }

  function renderDutyWeekly(container, weekly) {
    const sourceRef = weekly && weekly.source_ref;
    const { block, body } = makeDutyBlock('本周周报', sourceRef);
    if (weekly && weekly.exists && weekly.content) {
      const meta = document.createElement('div');
      meta.className = 'console-duty-meta';
      meta.textContent = [dutyText(weekly.week), dutyShortStamp(weekly.generated_at)]
        .concat(weeklyFrontmatterMeta(weekly.content))
        .filter(Boolean).join(' · ');
      markDutySource(meta, sourceRef);
      if (meta.textContent) body.appendChild(meta);

      const ASSERT_CAP = 8;
      let shown = 0;
      let total = 0;
      let currentGroup = null;
      dutyLines(weekly.content).forEach((ln) => {
        if (/^>/.test(ln)) return;
        const header = /^#{1,6}\s+(.+)$/.exec(ln);
        if (header) {
          currentGroup = header[1].trim();
          return;
        }
        const assert = parseDutyAssert(ln);
        if (!assert) return;
        total += 1;
        if (shown >= ASSERT_CAP) return;
        if (currentGroup) {
          const sub = document.createElement('div');
          sub.className = 'console-duty-assert-group';
          sub.textContent = currentGroup;
          body.appendChild(sub);
          currentGroup = null;
        }
        body.appendChild(makeDutyAssertion(assert, sourceRef));
        shown += 1;
      });
      if (total > shown) {
        const more = document.createElement('div');
        more.className = 'console-duty-assert-rest';
        more.textContent = '… 其余 ' + (total - shown) + ' 条断言在源文件';
        markDutySource(more, sourceRef);
        body.appendChild(more);
        body.appendChild(makeDutySourceButton(sourceRef));
      } else if (!shown) {
        body.appendChild(makeDutyEmpty('本周报无可解析断言', sourceRef));
      }
    } else {
      body.appendChild(makeDutyEmpty(dutyText(weekly && weekly.empty_state, '周五晚生成'), sourceRef));
    }
    container.appendChild(block);
  }

  function renderDutyAutogrant(container, receipt) {
    const sourceRef = receipt && receipt.source_ref;
    const { block, body } = makeDutyBlock('代批回执', sourceRef);
    const summary = document.createElement('div');
    summary.className = 'console-duty-summary';
    summary.textContent = [
      dutyText(receipt && receipt.week_start),
      dutyText(receipt && receipt.week_end),
    ].filter(Boolean).join('..') + ' · ' + (Number(receipt && receipt.count) || 0) + ' 行';
    markDutySource(summary, sourceRef);
    body.appendChild(summary);

    const entries = Array.isArray(receipt && receipt.recent_entries) ? receipt.recent_entries : [];
    if (!entries.length) {
      body.appendChild(makeDutyEmpty(dutyText(receipt && receipt.empty_state, '本周无代批'), sourceRef));
    } else {
      const list = document.createElement('div');
      list.className = 'console-duty-list';
      entries.forEach((entry) => {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'console-duty-row';
        markDutySource(row, entry.source_ref || sourceRef);
        row.onclick = () => openDutySource(entry.source_ref || sourceRef);
        const main = document.createElement('span');
        main.className = 'console-duty-row-main';
        main.textContent = [entry.date, entry.task_id, entry.title ? '《' + entry.title + '》' : ''].filter(Boolean).join(' · ');
        const meta = document.createElement('span');
        meta.className = 'console-duty-row-meta';
        meta.textContent = [entry.undo ? '撤销:' + entry.undo : '', entry.source].filter(Boolean).join(' · ');
        row.appendChild(main);
        row.appendChild(meta);
        list.appendChild(row);
      });
      body.appendChild(list);
    }
    container.appendChild(block);
  }

  // KAN-979：外发台账同 (channel,target,verdict) 相邻重复合并计数（×N 保真，数据一条不丢）；
  // verdict 用小色点表达——pass=绿(通过)，其余灰阶，不再逐字重复铺行。
  function dutyVerdictDotTone(verdict) {
    const v = String(verdict || '').toLowerCase();
    if (v === 'pass') return 'ok';
    if (v === 'hit') return 'ink';
    return 'muted';
  }

  function renderDutyOutbound(container, ledger) {
    const sourceRef = ledger && ledger.source_ref;
    const { block, body } = makeDutyBlock('外发台账尾巴', sourceRef);
    const entries = Array.isArray(ledger && ledger.entries) ? ledger.entries : [];
    if (!entries.length) {
      body.appendChild(makeDutyEmpty(dutyText(ledger && ledger.empty_state, '暂无外发台账记录'), sourceRef));
    } else {
      const merged = [];
      entries.forEach((entry) => {
        const key = [
          dutyText(entry.channel, 'general'),
          dutyText(entry.target, '未标目标'),
          dutyText(entry.verdict, 'unknown'),
        ].join('|');
        const last = merged[merged.length - 1];
        if (last && last.key === key) {
          last.count += 1;
          last.lastTs = entry.ts || last.lastTs;
          return;
        }
        merged.push({ key, entry, count: 1, lastTs: entry.ts });
      });
      const list = document.createElement('div');
      list.className = 'console-duty-list';
      merged.forEach((group) => {
        const entry = group.entry;
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'console-duty-row';
        markDutySource(row, entry.source_ref || sourceRef);
        row.onclick = () => openDutySource(entry.source_ref || sourceRef);
        const main = document.createElement('span');
        main.className = 'console-duty-row-main console-duty-row-flex';
        const dot = document.createElement('span');
        dot.className = 'console-duty-dot tone-' + dutyVerdictDotTone(entry.verdict);
        dot.title = 'verdict=' + dutyText(entry.verdict, 'unknown');
        const text = document.createElement('span');
        text.className = 'console-duty-row-text';
        text.textContent = [
          dutyText(entry.channel, 'general'),
          dutyText(entry.verdict, 'unknown'),
          dutyShortStamp(group.lastTs),
        ].filter(Boolean).join(' · ');
        main.appendChild(dot);
        main.appendChild(text);
        if (group.count > 1) {
          const times = document.createElement('span');
          times.className = 'console-duty-times';
          times.textContent = '×' + group.count;
          main.appendChild(times);
        }
        const meta = document.createElement('span');
        meta.className = 'console-duty-row-meta';
        meta.textContent = dutyText(entry.target, '未标目标');
        row.appendChild(main);
        row.appendChild(meta);
        list.appendChild(row);
      });
      body.appendChild(list);
    }
    container.appendChild(block);
  }

  // KAN-979：活跃决策条每条 = 标题 + 血统小徽章(owner-confirmed/ai-draft/未标) + 一行截断正文。
  // 血统三态沿用规则血统语法；徽章只用灰阶，等 Owner 追认的（ai-draft）给 accent。
  function dutyLineageBadgeModel(status) {
    const text = dutyText(status, '');
    if (/owner-confirmed|confirmed|已确认/i.test(text)) return { label: 'owner-confirmed', tone: 'ink' };
    if (/待追认|ai-draft/i.test(text)) return { label: 'ai-draft 待追认', tone: 'accent' };
    if (/owner-deferred|deferred/i.test(text)) return { label: 'owner-deferred', tone: 'muted' };
    return { label: text || '未标血统', tone: 'muted' };
  }

  function renderDutyActive(container, active) {
    const sourceRef = active && active.source_ref;
    const { block, body } = makeDutyBlock('活跃决策条', sourceRef);
    const entries = Array.isArray(active && active.entries) ? active.entries : [];
    if (!entries.length) {
      body.appendChild(makeDutyEmpty(dutyText(active && active.empty_state, '暂无活跃决策投影'), sourceRef));
    } else {
      const list = document.createElement('div');
      list.className = 'console-duty-list';
      entries.forEach((entry) => {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'console-duty-row';
        markDutySource(row, entry.source_ref || sourceRef);
        row.onclick = () => openDutySource(entry.source_ref || sourceRef);
        const main = document.createElement('span');
        main.className = 'console-duty-row-main console-duty-row-flex';
        const title = document.createElement('span');
        title.className = 'console-duty-row-text';
        title.textContent = dutyText(entry.label, '未命名');
        const lineage = dutyLineageBadgeModel(entry.status);
        const badge = document.createElement('span');
        badge.className = 'console-badge tone-' + lineage.tone;
        badge.textContent = lineage.label;
        badge.title = dutyText(entry.status, '未标状态');
        main.appendChild(title);
        main.appendChild(badge);
        const meta = document.createElement('span');
        meta.className = 'console-duty-row-meta';
        meta.textContent = dutyText(entry.body);
        row.appendChild(main);
        row.appendChild(meta);
        list.appendChild(row);
      });
      body.appendChild(list);
    }
    container.appendChild(block);
  }

  // KAN-1001 指针：值守面板已从调度台主列搬到顶层「治理」视图的「人闸值守」段——
  // 主干由 render-governance.js 收口成 3-6 行可证伪断言，本函数整体作为其「展开明细」折叠区内容复用
  // （经 ctx.renderBoard.governance.makeDutyPanel 取用）。调度台不再直接调用。
  function makeAttentionGateDutyPanel() {
    const section = document.createElement('section');
    section.id = 'console-attention_gate-duty';
    section.className = 'console-duty';
    const attention_gateMode = consoleAudienceIsAttentionGate();
    markConsoleAudience(section, attention_gateMode ? CONSOLE_AUDIENCE_ATTENTION_GATE : CONSOLE_AUDIENCE_OWNER);

    const head = document.createElement('div');
    head.className = 'console-duty-head';
    const title = document.createElement('h3');
    title.textContent = '值守';
    const meta = document.createElement('span');
    meta.className = 'console-duty-head-meta';
    meta.textContent = 'data-bound';
    head.appendChild(title);
    head.appendChild(meta);
    section.appendChild(head);

    const grid = document.createElement('div');
    grid.className = 'console-duty-grid';
    section.appendChild(grid);

    const state = uiState.attention_gateDuty || {};
    if (state.data && state.data.ok) {
      if (attention_gateMode) {
        renderDutyWeekly(grid, state.data.weekly_review);
        renderDutyAutogrant(grid, state.data.autogrant_receipt);
        renderDutyOutbound(grid, state.data.outbound_ledger);
        renderDutyActive(grid, state.data.active_decisions);
      } else {
        renderDutyWeeklyOwner(grid, state.data.weekly_review);
        renderDutyAutograntOwner(grid, state.data.autogrant_receipt);
        renderDutyOutboundOwner(grid, state.data.outbound_ledger);
        renderDutyActiveOwner(grid, state.data.active_decisions);
      }
      if (state.loadedAt) {
        meta.textContent = 'data-bound · ' + new Date(state.loadedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      }
    } else if (state.data && !state.data.ok) {
      grid.appendChild(makeDutyEmpty('读取值守数据失败: ' + dutyText(state.data.error, 'unknown'), null));
    } else {
      grid.appendChild(makeDutyEmpty('读取值守数据中', null));
      ensureAttentionGateDutyLoaded();
    }
    if (typeof lucide !== 'undefined') requestAnimationFrame(() => lucide.createIcons());
    return section;
  }

  function makeDomainCard(task) {
    const card = createCardEl(task);
    card.classList.add('domain-task-card');
    if (isDueNow(task)) card.classList.add('is-due-now');
    const line = document.createElement('div');
    line.className = 'domain-card-line';
    const status = document.createElement('span');
    status.textContent = SL[task.status || 'todo'] || task.status || '待办';
    const owner = document.createElement('span');
    owner.textContent = task.assignee || '未分配';
    const dueMeta = dueDateText(task.due_date, task.status);
    const due = document.createElement('span');
    due.textContent = dueMeta ? dueMeta.text : '无截止';
    if (dueMeta && dueMeta.overdue) due.classList.add('is-overdue');
    line.appendChild(status);
    line.appendChild(owner);
    line.appendChild(due);
    card.appendChild(line);
    return card;
  }

  function renderTeam() {
    const el = document.getElementById('vw-team');
    el.innerHTML = '';
    const grouped = {};
    sortTasks(dataState.tasks || []).forEach((task) => {
      const member = task.assignee || task.assigned || '未分配';
      if (!grouped[member]) grouped[member] = [];
      grouped[member].push(task);
    });

    Object.entries(grouped).sort().forEach(([member, items]) => {
      const doing = items.filter((task) => task.status === 'in-progress').length;
      const done = items.filter((task) => task.status === 'done').length;
      const sec = document.createElement('div');
      sec.className = 'mem-s';
      const hd = document.createElement('div');
      hd.className = 'mem-h';
      const av = document.createElement('div');
      av.className = 'mem-av';
      av.textContent = member[0];
      hd.appendChild(av);
      const nm = document.createElement('div');
      nm.className = 'mem-nm';
      nm.textContent = member;
      hd.appendChild(nm);
      const st = document.createElement('div');
      st.className = 'mem-st';
      st.textContent = doing + ' 进行中 / ' + done + ' 已完成';
      hd.appendChild(st);
      sec.appendChild(hd);
      const tasks = document.createElement('div');
      tasks.className = 'mem-tasks';
      items.forEach((task) => {
        const card = document.createElement('div');
        card.className = 'card';
        card.style.padding = '8px 12px';
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;flex-wrap:wrap';
        row.appendChild(makeDd(SL, task.status || 'todo', async (value) => updateTaskStatus(task, value)));
        const sp = document.createElement('span');
        sp.style.fontSize = '12px';
        sp.textContent = task.display_title || task.title || task.filename;
        sp.style.cursor = 'pointer';
        sp.onclick = (e) => {
          e.stopPropagation();
          ctx.renderDetail.openTaskDetail(task.path);
        };
        row.appendChild(sp);
        row.appendChild(makeDd(PL, task.priority || 'medium', async (value) => {
          if (await ctx.api.apiUpdate(task.path, 'priority', value)) {
            task.priority = value;
            ctx.api.refresh();
          }
        }));
        if (task.project) {
          const badge = document.createElement('span');
          badge.className = 'b b-proj';
          badge.textContent = task.project;
          row.appendChild(badge);
        }
        card.appendChild(row);
        tasks.appendChild(card);
      });
      sec.appendChild(tasks);
      el.appendChild(sec);
    });
  }

  function renderPipeline() {
    const el = document.getElementById('vw-pipeline');
    el.innerHTML = '';
    const STAGES = [
      { key: 'leads', label: '线索', desc: '初次接触、待评估' },
      { key: 'active', label: '进行中', desc: '已评估、开发中' },
      { key: 'delivered', label: '已交付', desc: '项目完成' },
    ];
    const grouped = { leads: [], active: [], delivered: [] };
    (dataState.client_docs || []).forEach((doc) => {
      const stage = doc.stage || 'leads';
      if (grouped[stage]) grouped[stage].push(doc);
    });
    const board = document.createElement('div');
    board.className = 'board board-pipeline';
    STAGES.forEach((stage) => {
      const items = grouped[stage.key] || [];
      const col = document.createElement('div');
      col.className = 'col';
      const hd = document.createElement('div');
      hd.className = 'col-hd';
      const lbl = document.createElement('span');
      lbl.textContent = stage.label;
      hd.appendChild(lbl);
      const cnt = document.createElement('span');
      cnt.className = 'cnt';
      cnt.textContent = items.length;
      hd.appendChild(cnt);
      col.appendChild(hd);
      if (items.length) {
        const bd = document.createElement('div');
        bd.className = 'col-bd';
        items.forEach((doc) => {
          const card = document.createElement('div');
          card.className = 'card';
          const title = document.createElement('div');
          title.className = 't';
          title.textContent = doc.client || doc.filename;
          card.appendChild(title);
          const meta = document.createElement('div');
          meta.className = 'm';
          if (doc.industry) {
            const b = document.createElement('span');
            b.className = 'b';
            b.style.cssText = 'background:var(--yellow2);color:var(--yellow)';
            b.textContent = doc.industry;
            meta.appendChild(b);
          }
          if (doc.channel) {
            const b = document.createElement('span');
            b.className = 'b';
            b.style.cssText = 'background:var(--blue2);color:var(--blue)';
            b.textContent = doc.channel;
            meta.appendChild(b);
          }
          card.appendChild(meta);
          bd.appendChild(card);
        });
        col.appendChild(bd);
      } else {
        const empty = document.createElement('div');
        empty.className = 'empty';
        empty.style.padding = '30px 16px';
        empty.textContent = stage.desc;
        col.appendChild(empty);
      }
      board.appendChild(col);
    });
    el.appendChild(board);
  }

  // ── 调度台（个人 AI 调度视图）──────────────────────────────
  // 设计哲学借自看板（文件即数据 / 任务卡 / 人保留验收权 / 场景联动），
  // 但组织轴从“状态”换成“我的注意力”：验收 → 今日必做 → 团队对接 + 数字同事花名册。

  Object.assign(board, {
    makeDutyBlock,
    makeDutyEmpty,
    dutyLines,
    dutyAssertLines,
    dutyFirstNumber,
    dutyCount,
    dutyCountText,
    makeDutyOwnerStatement,
    appendDutyOwnerStatements,
    weeklyDutyStatementModel,
    renderDutyWeeklyOwner,
    renderDutyAutograntOwner,
    renderDutyOutboundOwner,
    activeDutyStatusLabel,
    renderDutyActiveOwner,
    weeklyFrontmatterMeta,
    splitDutyAssertEvidence,
    parseDutyAssert,
    makeDutyAssertion,
    renderDutyWeekly,
    renderDutyAutogrant,
    dutyVerdictDotTone,
    renderDutyOutbound,
    dutyLineageBadgeModel,
    renderDutyActive,
    makeAttentionGateDutyPanel,
    makeDomainCard,
    renderTeam,
    renderPipeline
  });
  return board;
 }
