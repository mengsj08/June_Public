export function setupApi(ctx) {
  const { dataState, uiState, ui } = ctx;
  const { toast, SL } = ui;

  async function apiJson(input, init) {
    const response = await fetch(input, init);
    const contentType = response.headers && response.headers.get ? (response.headers.get('content-type') || '') : '';
    let json = null;
    if (contentType.includes('application/json')) {
      try {
        json = await response.json();
      } catch (e) {
        json = null;
      }
    }
    if (!json || typeof json !== 'object') {
      const message = response.ok ? '非 JSON 响应' : `HTTP ${response.status || ''}`.trim();
      json = { ok: false, error: message, message };
    }
    return { response, json };
  }

  function openInEditor(path) {
    if (!ctx.hasApi) {
      toast('静态模式：请使用 --serve 启动交互服务器', true);
      return;
    }
    apiJson('/api/open', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ path })
    }).then(({ json }) => {
      if (!json.ok) toast(json.error || '打开编辑器失败', true);
    }).catch(() => toast('网络错误', true));
  }

  async function apiUpdate(path, field, value) {
    if (!ctx.hasApi) {
      toast('静态模式：请使用 --serve 启动交互服务器', true);
      return false;
    }
    try {
      const { json } = await apiJson('/api/update', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ path, field, value })
      });
      if (json.ok) {
        toast(field === 'due_date' ? '已更新截止日期' : ('已更新: ' + (SL[value] || value)));
        return json;  // 返回完整响应，调用方可检查 new_path
      }
      toast(json.message || '更新失败', true);
      return false;
    } catch (e) {
      toast('网络错误', true);
      return false;
    }
  }

  async function apiCreate(project, title, assignee, priority, body, due_date, options = {}) {
    try {
      const payload = { project, title, assignee, priority, body, due_date };
      ['workdir', 'promoted_from', 'task_family', 'execution_profile', 'legacy_id'].forEach((key) => {
        if (options && options[key]) payload[key] = options[key];
      });
      const { json } = await apiJson('/api/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      if (json.ok) return json;
      toast(json.message || '创建失败', true);
      return false;
    } catch (e) {
      toast('网络错误', true);
      return false;
    }
  }

  async function deleteTask(path) {
    if (!ctx.hasApi) {
      toast('静态模式：请使用 --serve 启动交互服务器', true);
      return false;
    }
    try {
      const { json } = await apiJson('/api/task', {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ path })
      });
      if (json.ok) {
        toast('任务卡已归档到 .archive/');
        return json;
      }
      toast(json.error || json.message || '删除失败', true);
      return false;
    } catch (e) {
      toast('网络错误', true);
      return false;
    }
  }

  async function apiGenerateTitle(body) {
    try {
      const { json } = await apiJson('/api/generate-title', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ body })
      });
      return json;
    } catch (e) {
      return { ok: false, message: '网络错误' };
    }
  }

  async function toggleAcceptanceCheck(path, index, expectedText, checked) {
    if (!ctx.hasApi) {
      toast('静态模式：请使用 --serve 启动交互服务器', true);
      return { ok: false, error: 'static mode' };
    }
    try {
      const { response, json } = await apiJson('/api/toggle-check', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ path, index, expected_text: expectedText, checked })
      });
      json.status = response.status;
      if (!json.ok) {
        const message = response.status === 409
          ? '完成标准已变化，请刷新后重试'
          : (json.message || json.error || '更新完成标准失败');
        toast(message, true);
      }
      return json;
    } catch (e) {
      toast('网络错误', true);
      return { ok: false, error: 'network error' };
    }
  }

  async function updateAcceptanceSection(path, body) {
    if (!ctx.hasApi) {
      toast('静态模式：请使用 --serve 启动交互服务器', true);
      return { ok: false, error: 'static mode' };
    }
    try {
      const { response, json } = await apiJson('/api/update-section', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ path, section: '完成标准', body })
      });
      json.status = response.status;
      if (!json.ok) toast(json.message || json.error || '保存完成标准失败', true);
      return json;
    } catch (e) {
      toast('网络错误', true);
      return { ok: false, error: 'network error' };
    }
  }

  async function refresh() {
    if (!ctx.hasApi) return;
    try {
      const { json } = await apiJson('/api/data');
      Object.assign(dataState, json);
      if (ctx.runtime && typeof ctx.runtime.syncRuntimeUI === 'function') ctx.runtime.syncRuntimeUI();
      if (ctx.ai && typeof ctx.ai.syncCurrentTaskStatusForPath === 'function') ctx.ai.syncCurrentTaskStatusForPath();
      uiState.sync.state = json.git_sync || uiState.sync.state;
      if (ctx.renderBoard && typeof ctx.renderBoard.renderAll === 'function') ctx.renderBoard.renderAll();
      if (ctx.runtime && typeof ctx.runtime.renderSyncIndicator === 'function') ctx.runtime.renderSyncIndicator();
    } catch (e) {
      return null;
    }
    return null;
  }

  async function fetchTaskByPath(path) {
    try {
      const { json } = await apiJson('/api/task?path=' + encodeURIComponent(path));
      return json;
    } catch (e) {
      return { ok: false, error: 'network error' };
    }
  }

  async function fetchTaskByCode(code) {
    try {
      const { json } = await apiJson('/api/task?code=' + encodeURIComponent(code));
      return json;
    } catch (e) {
      return { ok: false, error: 'network error' };
    }
  }

  async function launchBridge(target) {
    if (!ctx.hasApi) {
      toast('静态模式：请使用 --serve 启动交互服务器', true);
      return { ok: false, error: 'static mode' };
    }
    try {
      const { json } = await apiJson('/api/bridges/launch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ target })
      });
      if (!json.ok) toast(json.error || '启动失败', true);
      return json;
    } catch (e) {
      toast('网络错误', true);
      return { ok: false, error: 'network error' };
    }
  }

  async function bridgeStatus() {
    if (!ctx.hasApi) return {};
    try {
      const { json } = await apiJson('/api/bridges/status');
      return json && typeof json === 'object' ? json : {};
    } catch (e) {
      return {};
    }
  }

  async function dynamicBoards() {
    if (!ctx.hasApi) return { ok: false, providers: [] };
    try {
      const { json } = await apiJson('/api/dynamic-boards');
      return json;
    } catch (e) {
      return { ok: false, error: 'network error', providers: [] };
    }
  }

  async function runDynamicBoard(id, options = {}) {
    if (!ctx.hasApi) return { ok: false, error: 'static mode' };
    try {
      const { json } = await apiJson('/api/dynamic-boards/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id, auto: options && options.auto === true })
      });
      if (!json.ok && !(options && options.auto)) toast(json.error || '动态看板刷新失败', true);
      return json;
    } catch (e) {
      toast('网络错误', true);
      return { ok: false, error: 'network error' };
    }
  }

  async function governanceProbe() {
    if (!ctx.hasApi) return { ok: false, error: 'static mode' };
    try {
      const { json } = await apiJson('/api/governance/probe');
      return json;
    } catch (e) {
      return { ok: false, error: 'network error' };
    }
  }

  async function governanceHealthcheckStatus() {
    if (!ctx.hasApi) return { ok: false, error: 'static mode' };
    try {
      const { response, json } = await apiJson('/api/governance/healthcheck/status');
      if (response && response.status === 404) {
        return {
          ok: true,
          stale_backend: true,
          error: json && json.error ? json.error : 'HTTP 404',
          latest: {
            health: '服务待重启',
            service_restart_required: true,
            failed_command_count: 0,
          },
        };
      }
      return json;
    } catch (e) {
      return { ok: false, error: 'network error' };
    }
  }

  async function governanceNoiseReview() {
    if (!ctx.hasApi) return { ok: false, error: 'static mode' };
    try {
      const { json } = await apiJson('/api/governance/noise-review', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({})
      });
      if (!json.ok) toast(json.error || '治理自检启动失败', true);
      return json;
    } catch (e) {
      toast('网络错误', true);
      return { ok: false, error: 'network error' };
    }
  }

  async function governanceNoiseReviewStatus() {
    if (!ctx.hasApi) return { ok: false, error: 'static mode' };
    try {
      const { json } = await apiJson('/api/governance/noise-review/status');
      return json;
    } catch (e) {
      return { ok: false, error: 'network error' };
    }
  }

  async function attention_gateDuty() {
    if (!ctx.hasApi) return { ok: false, error: 'static mode' };
    try {
      const { json } = await apiJson('/api/attention_gate/duty');
      return json;
    } catch (e) {
      return { ok: false, error: 'network error' };
    }
  }

  async function networkStatus() {
    if (!ctx.hasApi) return { ok: false, error: 'static mode' };
    try {
      const { json } = await apiJson('/api/network/status');
      return json;
    } catch (e) {
      return { ok: false, error: 'network error' };
    }
  }

  async function networkPreset(preset, confirmed) {
    if (!ctx.hasApi) return { ok: false, error: 'static mode' };
    try {
      const { json } = await apiJson('/api/network/preset', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ preset, confirmed: confirmed === true })
      });
      if (!json.ok) toast(json.error || '网络方案执行失败', true);
      return json;
    } catch (e) {
      toast('网络错误', true);
      return { ok: false, error: 'network error' };
    }
  }

  async function networkDoctor(action, confirmed) {
    if (!ctx.hasApi) return { ok: false, error: 'static mode' };
    try {
      const { json } = await apiJson('/api/network/doctor', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ action, confirmed: confirmed === true })
      });
      if (!json.ok) toast(json.error || '网络医生执行失败', true);
      return json;
    } catch (e) {
      toast('网络错误', true);
      return { ok: false, error: 'network error' };
    }
  }

  window.fetch = function(url, opts) {
    const next = opts || {};
    if (typeof url === 'string' && url.startsWith('/api/')) next.credentials = next.credentials || 'same-origin';
    return uiState.fetch.original(url, next).then((response) => {
      if (response.status === 401 && typeof url === 'string' && url.startsWith('/api/')) {
        response.clone().json().then((json) => {
          if (json.requireLogin && ctx.auth) ctx.auth.handleUnauthorized();
        }).catch(() => {});
      }
      return response;
    });
  };

  ctx.api = {
    apiJson,
    openInEditor,
    apiUpdate,
    apiCreate,
    deleteTask,
    apiGenerateTitle,
    toggleAcceptanceCheck,
    updateAcceptanceSection,
    refresh,
    fetchTaskByPath,
    fetchTaskByCode,
    launchBridge,
    bridgeStatus,
    dynamicBoards,
    runDynamicBoard,
    governanceProbe,
    governanceHealthcheckStatus,
    governanceNoiseReview,
    governanceNoiseReviewStatus,
    attention_gateDuty,
    networkStatus,
    networkPreset,
    networkDoctor,
  };

  return ctx.api;
}
