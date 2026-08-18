export function setupAuth(ctx) {
  const { dataState, uiState, ui } = ctx;
  const { dom, esc } = ui;

  function updateUserUI() {
    if (dom.hdrUsername) dom.hdrUsername.textContent = uiState.auth.currentUser || '未设置';
    if (dom.btnLogout) {
      if (uiState.auth.sessionValid) {
        dom.btnLogout.style.display = ui.isMobile() ? 'none' : '';
      } else {
        dom.btnLogout.style.display = 'none';
      }
    }
  }

  function syncAuthFromDataState() {
    const auth = dataState.auth || {};
    const user = String(auth.user || '').trim();
    if (auth.authenticated && user) {
      uiState.auth.currentUser = user;
      uiState.auth.sessionValid = true;
      updateUserUI();
      return true;
    }
    return false;
  }

  function showLogin(step) {
    dom.loginOverlay.classList.add('on');
    if (step === 'user') {
      dom.loginStepQuiz.classList.remove('on');
      dom.loginStepUser.classList.add('on');
      renderLoginMembers();
    } else {
      dom.loginStepQuiz.classList.add('on');
      dom.loginStepUser.classList.remove('on');
      setTimeout(() => dom.quizName.focus(), 100);
    }
  }

  function hideLogin() {
    dom.loginOverlay.classList.remove('on');
  }

  function renderLoginMembers() {
    const members = dataState.login_members || ['我'];
    uiState.auth.loginMembersRendered = true;
    dom.loginMembers.innerHTML = members.map((member) =>
      '<div class="login-member" data-user="' + esc(member) + '">' +
      '<div class="login-member-avatar">' + esc(member.charAt(0)) + '</div>' +
      '<div class="login-member-name">' + esc(member) + '</div></div>'
    ).join('');
    dom.loginMembers.querySelectorAll('.login-member').forEach((el) => {
      el.addEventListener('click', () => selectUser(el.dataset.user));
    });
  }

  function renderQuiz(question, options) {
    dom.quizQuestion.textContent = question || '';
    dom.quizOptions.innerHTML = '';
    (options || []).forEach((text, index) => {
      const label = document.createElement('label');
      label.className = 'quiz-option';
      label.innerHTML = '<input type="checkbox" value="' + index + '"><span>' + esc(text) + '</span>';
      const input = label.querySelector('input');
      input.addEventListener('change', () => {
        label.classList.toggle('selected', input.checked);
      });
      dom.quizOptions.appendChild(label);
    });
  }

  function renderAuthChallenge(json) {
    const mode = json.auth_mode === 'quiz' ? 'quiz' : 'token';
    uiState.auth.authMode = mode;
    dom.quizQuestion.textContent = json.question || '';
    dom.quizOptions.style.display = mode === 'quiz' ? '' : 'none';
    dom.quizCountdown.style.display = mode === 'quiz' ? '' : 'none';
    dom.quizCountdownHero.style.display = mode === 'quiz' ? '' : 'none';
    dom.quizName.type = mode === 'token' ? 'password' : 'text';
    dom.quizName.placeholder = mode === 'token' ? '本机访问 token' : '你是？';
    dom.quizName.autocomplete = mode === 'token' ? 'off' : 'name';
    dom.quizName.value = mode === 'quiz' ? (localStorage.getItem('kanban_quiz_name') || '') : '';
    renderQuiz(json.question, json.options || []);
  }

  function setQuizToast(message) {
    dom.quizToast.textContent = message;
    dom.quizToast.classList.add('show');
    setTimeout(() => dom.quizToast.classList.remove('show'), 1200);
  }

  function stopQuizCountdown() {
    if (uiState.auth.quizTimer) {
      clearInterval(uiState.auth.quizTimer);
      uiState.auth.quizTimer = null;
    }
    uiState.auth.quizDeadline = 0;
  }

  function startQuizCountdown() {
    stopQuizCountdown();
    uiState.auth.quizDeadline = Date.now() + 60000;
    const tick = () => {
      const remain = Math.max(0, Math.ceil((uiState.auth.quizDeadline - Date.now()) / 1000));
      const mm = String(Math.floor(remain / 60)).padStart(2, '0');
      const ss = String(remain % 60).padStart(2, '0');
      const display = mm + ':' + ss;
      dom.quizCountdown.textContent = display;
      dom.quizCountdownHero.textContent = display;
      dom.quizCountdownHero.classList.toggle('urgent', remain <= 10);
      if (remain <= 0) {
        stopQuizCountdown();
        setQuizToast('已超时');
        fetchQuizAndShow(true);
      }
    };
    tick();
    uiState.auth.quizTimer = setInterval(tick, 250);
  }

  async function fetchQuizAndShow(isRefresh) {
    const refreshSeq = ++uiState.auth.quizRefreshSeq;
    const errEl = dom.quizError;
    const shouldPreserveCard = Boolean(isRefresh && dom.quizOptions.childElementCount);
    stopQuizCountdown();
    uiState.auth.quizToken = '';
    if (!shouldPreserveCard) {
      errEl.textContent = '';
      dom.quizOptions.innerHTML = '';
      dom.quizName.value = uiState.auth.authMode === 'quiz'
        ? (localStorage.getItem('kanban_quiz_name') || '') : '';
    }
    dom.quizSubmit.disabled = false;
    dom.quizSubmit.textContent = '提交';
    showLogin('quiz');
    try {
      const response = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}',
        credentials: 'same-origin'
      });
      const json = await response.json();
      if (refreshSeq !== uiState.auth.quizRefreshSeq) return;
      if (json.ok) {
        dom.loginOverlay.classList.add('on');
        errEl.textContent = '';
        dom.quizOptions.innerHTML = '';
        dom.quizName.value = '';
        dom.quizSubmit.disabled = false;
        uiState.auth.quizToken = json.quiz_token || '';
        renderAuthChallenge(json);
        if (uiState.auth.authMode === 'quiz') startQuizCountdown();
        setTimeout(() => dom.quizName.focus(), 80);
      } else {
        errEl.textContent = json.error || '获取测验失败';
        dom.quizSubmit.disabled = Boolean(json.retry_after);
      }
    } catch (e) {
      if (refreshSeq !== uiState.auth.quizRefreshSeq) return;
      errEl.textContent = '网络错误';
      dom.quizSubmit.disabled = false;
    }
  }

  async function selectUser(user) {
    try {
      const response = await fetch('/api/select-user', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ user }),
        credentials: 'same-origin'
      });
      const json = await response.json();
      if (json.ok) {
        uiState.auth.currentUser = json.user || user;
        uiState.auth.sessionValid = true;
        hideLogin();
        updateUserUI();
        loadDataAfterLogin();
      }
    } catch (e) {
      console.error('选择用户失败', e);
    }
  }

  async function handleQuizSubmit() {
    const errEl = dom.quizError;
    const credential = dom.quizName.value.trim();
    const tokenMode = uiState.auth.authMode !== 'quiz';
    const selected = Array.from(document.querySelectorAll('#quiz-options input[type="checkbox"]:checked'))
      .map((el) => Number(el.value))
      .filter(Number.isInteger);
    if (!tokenMode && !selected.length) {
      errEl.textContent = '请至少选择一个选项';
      return;
    }
    if (!credential) {
      errEl.textContent = tokenMode ? '请输入本机访问 token' : '请输入姓名';
      return;
    }
    errEl.textContent = '';
    dom.quizSubmit.disabled = true;
    dom.quizSubmit.textContent = '验证中...';
    try {
      const response = await fetch(tokenMode ? '/api/verify-token' : '/api/verify-quiz', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(tokenMode
          ? { access_token: credential }
          : { quiz_token: uiState.auth.quizToken, selected, name: credential }),
        credentials: 'same-origin'
      });
      const json = await response.json();
      if (json.ok) {
        stopQuizCountdown();
        if (!tokenMode) localStorage.setItem('kanban_quiz_name', credential);
        uiState.auth.currentUser = json.user || '';
        uiState.auth.sessionValid = true;
        uiState.auth.quizToken = '';
        hideLogin();
        updateUserUI();
        await loadDataAfterLogin();
        return;
      }
      if (!tokenMode && json.error === '测验已过期，请刷新页面') {
        errEl.textContent = '';
        setQuizToast('已超时');
        fetchQuizAndShow(true);
        return;
      }
      errEl.textContent = json.error || '验证失败';
      stopQuizCountdown();
      if (!tokenMode) setTimeout(() => fetchQuizAndShow(true), 1500);
    } catch (e) {
      errEl.textContent = '网络错误';
    } finally {
      dom.quizSubmit.disabled = false;
      dom.quizSubmit.textContent = '提交';
    }
  }

  async function loadDataAfterLogin() {
    try {
      const response = await fetch('/api/data', { credentials: 'same-origin' });
      const data = await response.json();
      Object.assign(dataState, data);
      syncAuthFromDataState();
      if (ctx.runtime && typeof ctx.runtime.syncRuntimeUI === 'function') ctx.runtime.syncRuntimeUI();
      if (uiState.auth.loginMembersRendered) renderLoginMembers();
      if (ctx.renderBoard) ctx.renderBoard.renderAll();
      if (ctx.renderDetail && typeof ctx.renderDetail.checkHashAndOpenDetail === 'function') {
        ctx.renderDetail.checkHashAndOpenDetail();
      }
    } catch (e) {
      console.error('加载数据失败', e);
    }
  }

  async function logout() {
    try {
      await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' });
    } catch (e) {
      console.error('退出登录请求失败', e);
    }
    uiState.auth.currentUser = '';
    uiState.auth.sessionValid = false;
    uiState.auth.quizToken = '';
    stopQuizCountdown();
    updateUserUI();
    fetchQuizAndShow();
    return null;
  }

  function handleUnauthorized() {
    uiState.auth.currentUser = '';
    uiState.auth.sessionValid = false;
    updateUserUI();
    fetchQuizAndShow();
  }

  function bindEvents() {
    dom.quizSubmit.addEventListener('click', handleQuizSubmit);
    dom.quizName.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleQuizSubmit();
    });
    dom.quizName.addEventListener('input', (e) => {
      if (uiState.auth.authMode === 'quiz') {
        localStorage.setItem('kanban_quiz_name', e.target.value);
      }
    });
    // KAN-203：顶栏「退出」按钮已收进汉堡菜单（overflow-logout），顶级按钮可缺省，故 null-safe。
    if (dom.btnLogout) dom.btnLogout.addEventListener('click', logout);
    dom.overflowLogout.addEventListener('click', logout);
    dom.overflowSwitchUser.addEventListener('click', () => {
      if (uiState.auth.sessionValid) showLogin('user');
    });
    dom.loginUserClose.addEventListener('click', () => {
      if (uiState.auth.sessionValid) hideLogin();
    });
  }

  function init() {
    if (!syncAuthFromDataState()) {
      fetchQuizAndShow();
    }
  }

  ctx.auth = {
    updateUserUI,
    syncAuthFromDataState,
    showLogin,
    hideLogin,
    renderLoginMembers,
    fetchQuizAndShow,
    selectUser,
    handleQuizSubmit,
    loadDataAfterLogin,
    logout,
    handleUnauthorized,
    bindEvents,
    init,
  };

  return ctx.auth;
}
