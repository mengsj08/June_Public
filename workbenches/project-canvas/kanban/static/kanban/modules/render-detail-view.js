// KAN-1671: mounted by main.js; dependencies arrive through ctx.renderDetailInternal.
export function setupRenderDetailView(ctx) {
  const detail = ctx.renderDetailInternal;
  if (!detail) throw new Error('setupRenderDetail(ctx) must run first');
  const { dataState, uiState, ui, markdown } = ctx;
  const {
    detailOverlay, detailTitle, detailLoading, detailError, detailBodyArea, detailMdContent,
    detailProps, detailFilePath, detailCopyBtn, detailSidebar, detailStatusBar,
    detailEditor, detailViewMode, detailEditMode, editorStatus, detailEditBtn,
    aiActivity, aiActivityList, detailSidebarInfoTab, detailSidebarCommentsTab,
    detailSidebarCommentsBadge, detailSidebarFoldBtn, detailSidebarInfo, detailSidebarComments,
  } = ctx.el;
  const { SL, PL, FLATPICKR_LOCALE, isMobile, dueDateText, toast, makeDd, makeMemberDd } = ui;
  const { detailState } = detail;
  const syncEditModeUI = (...args) => detail.syncEditModeUI(...args);
  const _detailSidebarState = (...args) => detail._detailSidebarState(...args);
  const setSidebarTab = (...args) => detail.setSidebarTab(...args);
  const setSidebarFolded = (...args) => detail.setSidebarFolded(...args);
  const _shortText = (...args) => detail._shortText(...args);
  const _safeExternalCommentUrl = (...args) => detail._safeExternalCommentUrl(...args);
  const _formatExternalCommentTime = (...args) => detail._formatExternalCommentTime(...args);
  const _externalCommentView = (...args) => detail._externalCommentView(...args);
  const _mergeConcurrentComment = (...args) => detail._mergeConcurrentComment(...args);
  const _externalEditButton = (...args) => detail._externalEditButton(...args);
  const _jumpToExternalCommentSource = (...args) => detail._jumpToExternalCommentSource(...args);
  const loadTaskComments = (...args) => detail.loadTaskComments(...args);
  const jumpToCommentAnchor = (...args) => detail.jumpToCommentAnchor(...args);
  const refreshCommentSidebarAvailability = (...args) => detail.refreshCommentSidebarAvailability(...args);
  const renderCommentSidebar = (...args) => detail.renderCommentSidebar(...args);
  const normalizeDuplicateCommentAnchors = (...args) => detail.normalizeDuplicateCommentAnchors(...args);
  const openCommentSidebar = (...args) => detail.openCommentSidebar(...args);
  const destroyDetailDuePicker = (...args) => detail.destroyDetailDuePicker(...args);
  const restoreCurrentTaskLocation = (...args) => detail.restoreCurrentTaskLocation(...args);
  const updateEditorStatus = (...args) => detail.updateEditorStatus(...args);
  const _blockTrailer = (...args) => detail._blockTrailer(...args);
  const _renderDetailBlock = (...args) => detail._renderDetailBlock(...args);
  const _renderTaskBodyBlocks = (...args) => detail._renderTaskBodyBlocks(...args);
  const _restoreInlineEditor = (...args) => detail._restoreInlineEditor(...args);
  const _persistInlineBody = (...args) => detail._persistInlineBody(...args);
  const commitInlineBlockEdit = (...args) => detail.commitInlineBlockEdit(...args);
  const deleteInlineBlock = (...args) => detail.deleteInlineBlock(...args);
  const _autosizeInlineEditor = (...args) => detail._autosizeInlineEditor(...args);
  const enterInlineBlockEdit = (...args) => detail.enterInlineBlockEdit(...args);
  const closeDetail = (...args) => detail.closeDetail(...args);
  const _openDetail = (...args) => detail._openDetail(...args);
  const openTaskDetail = (...args) => detail.openTaskDetail(...args);
  const openTaskDetailByCode = (...args) => detail.openTaskDetailByCode(...args);
  const updateDetailField = (...args) => detail.updateDetailField(...args);
  const archiveCurrentTask = (...args) => detail.archiveCurrentTask(...args);
  const openDetailDuePicker = (...args) => detail.openDetailDuePicker(...args);
  const extractAcceptanceSection = (...args) => detail.extractAcceptanceSection(...args);
  const stripAcceptanceSection = (...args) => detail.stripAcceptanceSection(...args);
  const parseAcceptanceChecks = (...args) => detail.parseAcceptanceChecks(...args);
  const refreshCurrentDetailTask = (...args) => detail.refreshCurrentDetailTask(...args);
  const bindAcceptanceCheckboxes = (...args) => detail.bindAcceptanceCheckboxes(...args);
  const renderAcceptanceEditor = (...args) => detail.renderAcceptanceEditor(...args);
  const prependAcceptanceBlock = (...args) => detail.prependAcceptanceBlock(...args);
  const stripCardNoteSection = (...args) => detail.stripCardNoteSection(...args);
  const prependCardNoteBlock = (...args) => detail.prependCardNoteBlock(...args);
  const appendTeamHandoffStatus = (...args) => detail.appendTeamHandoffStatus(...args);
  const isDateAfter = (...args) => detail.isDateAfter(...args);
  const copyTextWithFallback = (...args) => detail.copyTextWithFallback(...args);
  const appendLandingPropRow = (...args) => detail.appendLandingPropRow(...args);
  const appendLandingAiPlaceholder = (...args) => detail.appendLandingAiPlaceholder(...args);
  const appendLandingPageStatus = (...args) => detail.appendLandingPageStatus(...args);
  const lineageLabel = (...args) => detail.lineageLabel(...args);
  const factKindLabel = (...args) => detail.factKindLabel(...args);
  const lineageMeta = (...args) => detail.lineageMeta(...args);
  const appendActivitySourceHistory = (...args) => detail.appendActivitySourceHistory(...args);
  const projectFromTask = (...args) => detail.projectFromTask(...args);
  const childTaskBody = (...args) => detail.childTaskBody(...args);
  const deriveChildTask = (...args) => detail.deriveChildTask(...args);
  const appendNextStepRelay = (...args) => detail.appendNextStepRelay(...args);
  const appendDangerZone = (...args) => detail.appendDangerZone(...args);
  function renderDetailContent(task) {
    destroyDetailDuePicker();
    detailState.currentDetailTask = task;
    detailState.activeDetailBlockEditor = null;
    detailState.inlineBlockSavePromise = null;
    uiState.detail.inlineEditing = false;
    uiState.detail.inlineSaving = false;
    uiState.detail.editorDirty = false;
    uiState.detail.acceptanceDirty = false;
    uiState.detail.noteDirty = false;
    uiState.detail.currentTaskRaw = task.raw || '';
    uiState.detail.currentTaskPath = task.path || '';
    uiState.detail.currentTaskBody = task.body || '';
    uiState.detail.currentTaskStatus = task.status || 'todo';
    uiState.detail.currentTaskRev = task.rev || '';

    detailTitle.textContent = task.title || task.filename || '未命名';

    if (isMobile() && detailStatusBar) {
      detailStatusBar.innerHTML = '';
      const sDot = document.createElement('span');
      sDot.className = 'b b-' + (task.status || 'todo');
      sDot.textContent = SL[task.status] || '待办';
      detailStatusBar.appendChild(sDot);
      const pDot = document.createElement('span');
      pDot.className = 'b b-' + (task.priority || 'medium');
      pDot.textContent = PL[task.priority] || '中';
      detailStatusBar.appendChild(pDot);
      if (task.assignee) {
        const who = document.createElement('span');
        who.className = 'b b-who';
        who.textContent = task.assignee;
        detailStatusBar.appendChild(who);
      }
      const dm = dueDateText(task.due_date, task.status);
      if (dm) {
        const due = document.createElement('span');
        due.className = 'due' + (dm.overdue ? ' overdue' : '');
        due.textContent = dm.text;
        detailStatusBar.appendChild(due);
      }
      detailStatusBar.onclick = () => {
        detailSidebar.classList.remove('collapsed');
        setSidebarFolded(false);
      };
      detailStatusBar.style.cursor = 'pointer';
    }

    const body = task.body || '';
    _renderTaskBodyBlocks(body, task);
    const commentSidebarState = _detailSidebarState();
    commentSidebarState.bodyCommentQuotes = normalizeDuplicateCommentAnchors(markdown.extractCommentQuotes(body));
    renderCommentSidebar(commentSidebarState.bodyCommentQuotes);
    loadTaskComments(task.path || '');

    detailProps.innerHTML = '';
    const metaTitle = document.createElement('div');
    metaTitle.className = 'detail-meta-title';
    metaTitle.textContent = 'Frontmatter';
    detailProps.appendChild(metaTitle);
    const props = [
      { label: '状态', value: task.status, type: 'status' },
      { label: '类型', value: task.kind || 'task', type: 'static' },
      { label: '领域', value: task.domain || 'personal', type: 'static' },
      { label: '优先级', value: task.priority, type: 'priority' },
      { label: '负责人', value: task.assignee, type: 'assignee' },
      { label: '截止日期', value: task.due_date, type: 'due_date' },
      { label: '项目', value: task.project, type: 'static' },
      { label: '工作目录', value: task.workdir, type: 'path' },
      { label: 'source_path', value: task.source_path, type: 'path', optional: true },
      { label: 'skill_refs', value: task.skill_refs, type: 'static', optional: true },
      { label: '创建', value: task.created, type: 'static' },
      { label: '更新', value: task.updated, type: 'static' },
    ].filter((prop) => !prop.optional || prop.value);

    props.forEach((prop) => {
      const row = document.createElement('div');
      row.className = 'detail-prop-row';
      const lbl = document.createElement('span');
      lbl.className = 'detail-prop-label';
      lbl.textContent = prop.label;
      row.appendChild(lbl);

      if (prop.type === 'status') {
        const valWrap = document.createElement('span');
        valWrap.className = 'detail-prop-value';
        valWrap.appendChild(makeDd(SL, prop.value || 'todo', async (value) => {
          if (!ctx.hasApi) return;
          try {
            const { json } = await ctx.api.apiJson('/api/update', {
              method: 'PUT',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ path: task.path, field: 'status', value })
            });
            if (json.ok) {
              uiState.detail.currentTaskStatus = value;
              if (ctx.ai) ctx.ai.updateAiButtonsState();
              await ctx.api.refresh();
              try {
                const j2 = await ctx.api.fetchTaskByPath(task.path);
                if (j2.ok) renderDetailContent(j2.task);
              } catch (e) {
                return null;
              }
              if (json.killed_entries && json.killed_entries.length > 0) {
                toast('任务已完成，已自动终止 AI 进程');
              } else {
                toast('已更新: ' + SL[value]);
              }
            } else {
              toast(json.message || '更新失败', true);
            }
          } catch (e) {
            toast('网络错误', true);
          }
        }));
        row.appendChild(valWrap);
      } else if (prop.type === 'priority') {
        const valWrap = document.createElement('span');
        valWrap.className = 'detail-prop-value';
        valWrap.appendChild(makeDd(PL, prop.value || 'medium', async (value) => {
          await updateDetailField(task, 'priority', value);
        }));
        row.appendChild(valWrap);
      } else if (prop.type === 'assignee') {
        const valWrap = document.createElement('span');
        valWrap.className = 'detail-prop-value';
        valWrap.appendChild(makeMemberDd(prop.value, dataState.all_members || dataState.members, async (value) => {
          await updateDetailField(task, 'assignee', value);
        }));
        row.appendChild(valWrap);
      } else if (prop.type === 'due_date') {
        const valWrap = document.createElement('span');
        valWrap.className = 'detail-prop-value';
        const val = document.createElement('span');
        const dueMeta = dueDateText(prop.value, task.status);
        if (task.status === 'done') {
          val.className = 'detail-prop-static';
          val.textContent = prop.value || '-';
        } else {
          val.className = 'detail-due-clickable' + (!prop.value ? ' detail-due-empty' : '') + (dueMeta && dueMeta.overdue ? ' detail-due-overdue' : '');
          val.textContent = prop.value ? (dueMeta ? prop.value + ' · ' + dueMeta.text : prop.value) : '设置截止日期';
          val.title = prop.value ? '点击修改截止日期' : '点击设置截止日期';
          val.onclick = () => openDetailDuePicker(val, task);
        }
        valWrap.appendChild(val);
        row.appendChild(valWrap);
      } else {
        const val = document.createElement('span');
        val.className = 'detail-prop-static';
        val.textContent = prop.value || '-';
        if (prop.type === 'path' && prop.value) {
          val.className += ' detail-prop-clickable';
          val.title = '点击打开: ' + prop.value;
          val.tabIndex = 0;
          val.onclick = () => ctx.api.openInEditor(prop.value);
          val.onkeydown = (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              ctx.api.openInEditor(prop.value);
            }
          };
        }
        row.appendChild(val);
      }

      detailProps.appendChild(row);
    });

    if (task.tags && task.tags.length) {
      const tagRow = document.createElement('div');
      tagRow.className = 'detail-prop-row';
      const lbl = document.createElement('span');
      lbl.className = 'detail-prop-label';
      lbl.textContent = '标签';
      tagRow.appendChild(lbl);
      const tagsWrap = document.createElement('span');
      tagsWrap.className = 'detail-prop-value detail-tags-wrap';
      task.tags.forEach((tag) => {
        const b = document.createElement('span');
        b.className = 'b b-tag';
        b.textContent = '#' + tag;
        tagsWrap.appendChild(b);
      });
      tagRow.appendChild(tagsWrap);
      detailProps.appendChild(tagRow);
    }

    appendTeamHandoffStatus(task);
    appendLandingPageStatus(task);
    appendActivitySourceHistory(task);
    appendNextStepRelay(task);
    appendDangerZone(task);

    detailFilePath.textContent = task.path;
    detailFilePath.onclick = () => ctx.api.openInEditor(task.path);

    const sidebarState = _detailSidebarState();
    setSidebarTab(sidebarState.sidebarTab, false);
    setSidebarFolded(sidebarState.sidebarFolded, false);
    if (isMobile()) detailSidebar.classList.add('collapsed');

    detailBodyArea.style.display = 'flex';
    syncEditModeUI();

    if (uiState.detail.openCommentsAfterSave) {
      uiState.detail.openCommentsAfterSave = false;
      openCommentSidebar(uiState.detail.commentQuotes.length
        ? uiState.detail.commentQuotes[uiState.detail.commentQuotes.length - 1].anchorKey
        : '');
    }

    if (ctx.hasApi && task.path && ctx.ai) ctx.ai.loadAiHistory(task.path);

    if (task.task_id) {
      uiState.detail.currentTaskHash = '#' + task.task_id;
      history.pushState(null, '', uiState.detail.currentTaskHash);
    } else {
      uiState.detail.currentTaskHash = '';
    }

    if (ctx.ai) ctx.ai.updateAiButtonsState();
  }

  async function enterEditMode() {
    if (uiState.detail.acceptanceDirty && !confirm('有未保存的完成标准更改，确定放弃并编辑全文吗？')) return;
    if (detailState.activeDetailBlockEditor || detailState.inlineBlockSavePromise) {
      const saved = detailState.activeDetailBlockEditor
        ? await commitInlineBlockEdit(false)
        : await detailState.inlineBlockSavePromise;
      if (!saved) return;
    }
    uiState.detail.acceptanceDirty = false;
    uiState.detail.isEditMode = true;
    uiState.detail.editorDirty = false;
    uiState.detail.savedBodyContent = uiState.detail.currentTaskBody;
    detailEditor.value = uiState.detail.savedBodyContent;
    syncEditModeUI();
    updateEditorStatus('', '');
    if (ctx.ai && typeof ctx.ai.onDetailEditModeChange === 'function') ctx.ai.onDetailEditModeChange(true);
    if (!detailEditor.dataset.fmBound) {
      detailEditor.dataset.fmBound = 'true';
      detailEditor.addEventListener('input', markdown._fmHandleInput);
      detailEditor.addEventListener('keydown', markdown._fmHandleKeydown, true);
      detailEditor.addEventListener('blur', () => {
        setTimeout(() => { if (uiState.fileMention.visible) markdown._fmHide(); }, 200);
      });
    }
    detailEditor.focus();
  }

  function exitEditMode() {
    if (uiState.detail.editorDirty && !confirm('有未保存的更改，确定要放弃吗？')) return;
    uiState.detail.isEditMode = false;
    uiState.detail.editorDirty = false;
    uiState.detail.openCommentsAfterSave = false;
    syncEditModeUI();
    updateEditorStatus('', '');
    if (ctx.ai && typeof ctx.ai.onDetailEditModeChange === 'function') ctx.ai.onDetailEditModeChange(false);
  }

  async function saveBody() {
    if (!uiState.detail.currentTaskPath || uiState.detail.isSavingBody) return;
    const saveBtn = ctx.el.editorSaveBtn;
    uiState.detail.isSavingBody = true;
    saveBtn.disabled = true;
    try {
      if (uiState.pendingUploadTasks.size) {
        updateEditorStatus('saving', '等待图片上传完成...');
        await markdown._waitForPendingUploads();
      }
      const newBody = detailEditor.value;
      if (newBody === uiState.detail.savedBodyContent) {
        toast('没有修改需要保存');
        return;
      }
      updateEditorStatus('saving', '保存中...');
      const { json } = await ctx.api.apiJson('/api/update-body', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: uiState.detail.currentTaskPath,
          body: newBody,
          base_rev: uiState.detail.currentTaskRev,
          base_body: uiState.detail.savedBodyContent
        })
      });
      if (json.ok) {
        uiState.detail.currentTaskBody = json.body || newBody;
        uiState.detail.savedBodyContent = json.body || newBody;
        uiState.detail.currentTaskRev = json.rev || uiState.detail.currentTaskRev;
        uiState.detail.editorDirty = false;
        updateEditorStatus('saved', json.merged ? '已合并保存' : '已保存');
        const taskJ = await ctx.api.fetchTaskByPath(uiState.detail.currentTaskPath);
        if (taskJ.ok) renderDetailContent(taskJ.task);
        ctx.api.refresh();
        uiState.sync.pendingRemoteRefresh = false;
        uiState.detail.isEditMode = false;
        syncEditModeUI();
        toast(json.merged ? '内容已自动合并并保存' : '内容已保存');
      } else if (json.conflict) {
        detailEditor.value = json.body || detailEditor.value;
        uiState.detail.currentTaskRev = json.rev || uiState.detail.currentTaskRev;
        uiState.detail.editorDirty = true;
        updateEditorStatus('dirty', '存在冲突，需手动处理');
        toast(json.message || '保存出现冲突', true);
      } else {
        updateEditorStatus('dirty', '保存失败');
        toast(json.message || '保存失败', true);
      }
    } catch (e) {
      updateEditorStatus('dirty', '网络错误');
      toast('网络错误', true);
    } finally {
      uiState.detail.isSavingBody = false;
      saveBtn.disabled = false;
    }
  }

  function checkHashAndOpenDetail() {
    if (markdown._guardPendingUploads('切换任务')) {
      restoreCurrentTaskLocation();
      return;
    }
    const hash = window.location.hash.slice(1);
    if (!hash) return;
    if (hash === 'runtime') {
      history.replaceState(null, '', window.location.pathname + window.location.search);
      return;
    }
    const codeMatch = hash.match(/^[A-Z]{3}-\d+$/);
    if (codeMatch) {
      openTaskDetailByCode(hash);
    } else {
      openTaskDetail(decodeURIComponent(hash));
    }
  }

  function bindEvents() {
    ctx.el.detailBackBtn.onclick = async () => {
      if (detailState.activeDetailBlockEditor || detailState.inlineBlockSavePromise) {
        const saved = detailState.activeDetailBlockEditor
          ? await commitInlineBlockEdit(false)
          : await detailState.inlineBlockSavePromise;
        if (!saved) return;
      }
      closeDetail();
    };
    ctx.el.detailQueueBtn.onclick = () => { if (ctx.ai) ctx.ai.openQueueSidebar(); };
    ctx.el.detailSidebarToggle.onclick = () => {
      const nextCollapsed = !detailSidebar.classList.contains('collapsed');
      detailSidebar.classList.toggle('collapsed', nextCollapsed);
      ctx.el.detailSidebarToggle.setAttribute('aria-expanded', nextCollapsed ? 'false' : 'true');
      if (!nextCollapsed) setSidebarFolded(false);
    };
    detailSidebarInfoTab.onclick = () => {
      setSidebarTab('info');
      setSidebarFolded(false);
    };
    detailSidebarCommentsTab.onclick = () => {
      setSidebarTab('comments');
      setSidebarFolded(false);
    };
    detailSidebarFoldBtn.onclick = () => setSidebarFolded(!detailSidebar.classList.contains('is-folded'));
    detailEditBtn.onclick = async () => {
      if (uiState.detail.isEditMode) exitEditMode();
      else await enterEditMode();
    };
    detailMdContent.addEventListener('click', async (event) => {
      if (uiState.detail.isEditMode || uiState.detail.inlineSaving) return;
      if (event.target.closest('.detail-block-editor')) return;
      if (event.target.closest('.detail-acceptance-block, .detail-note-block')) return;
      if (event.target.closest('a[href], button, input, select, textarea, .comment-anchor-mark')) return;
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed) return;
      const wrap = event.target.closest('.detail-doc-block');
      if (!wrap || wrap.classList.contains('is-editing')) return;
      await enterInlineBlockEdit(wrap);
    });
    ctx.el.editorSaveBtn.onclick = saveBody;
    ctx.el.editorCancelBtn.onclick = exitEditMode;
    detailEditor.addEventListener('input', function() {
      const isDirty = this.value !== uiState.detail.savedBodyContent;
      uiState.detail.editorDirty = isDirty;
      updateEditorStatus(isDirty ? 'dirty' : '', isDirty ? '未保存' : '');
    });
    detailEditor.addEventListener('keydown', function(e) {
      if (e.key === 'Tab') {
        e.preventDefault();
        const start = this.selectionStart;
        const end = this.selectionEnd;
        this.value = this.value.substring(0, start) + '  ' + this.value.substring(end);
        this.selectionStart = this.selectionEnd = start + 2;
        this.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    detailEditor.addEventListener('paste', async function(e) {
      const items = Array.from((e.clipboardData && e.clipboardData.items) || []);
      const files = items.filter((item) => item.kind === 'file' && item.type.startsWith('image/')).map((item) => item.getAsFile()).filter(Boolean);
      if (!files.length) return;
      e.preventDefault();
      await markdown.uploadImagesAndInsert(files, this);
    });
    detailEditor.addEventListener('dragover', function(e) {
      const hasImage = Array.from(e.dataTransfer?.items || []).some((item) => item.kind === 'file' && item.type.startsWith('image/'));
      if (!hasImage) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });
    detailEditor.addEventListener('drop', async function(e) {
      const files = Array.from(e.dataTransfer?.files || []).filter((file) => file.type.startsWith('image/'));
      if (!files.length) return;
      e.preventDefault();
      await markdown.uploadImagesAndInsert(files, this);
    });

    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && uiState.detail.isEditMode) {
        e.preventDefault();
        saveBody();
        return;
      }
      if (e.key === 'Escape') {
        if (ctx.el.lightboxOverlay.classList.contains('on')) {
          markdown.closeLightbox();
        } else if (uiState.detail.isEditMode) {
          exitEditMode();
        } else if (ctx.el.queueSidebar.classList.contains('on')) {
          if (ctx.ai) ctx.ai.closeQueueSidebar();
        } else if (detailOverlay.classList.contains('on')) {
          closeDetail();
        }
      }
    });

    detailCopyBtn.onclick = () => {
      if (!uiState.detail.currentTaskRaw) return;
      navigator.clipboard.writeText(uiState.detail.currentTaskRaw).then(() => {
        toast('已复制 Markdown 内容');
      }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = uiState.detail.currentTaskRaw;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        toast('已复制 Markdown 内容');
      });
    };

    window.addEventListener('beforeunload', (e) => {
      if (uiState.detail.editorDirty || uiState.detail.acceptanceDirty || markdown._hasPendingUploads()) {
        e.preventDefault();
        e.returnValue = '';
      }
    });

    window.addEventListener('popstate', () => {
      if (markdown._guardPendingUploads('切换任务')) {
        restoreCurrentTaskLocation();
        return;
      }
      if (detailOverlay.classList.contains('on')) {
        const hash = window.location.hash.slice(1);
        if (hash) return;
        closeDetail();
      }
    });

    window.addEventListener('hashchange', checkHashAndOpenDetail);
  }

  Object.assign(detail, { renderDetailContent, enterEditMode, exitEditMode, saveBody, checkHashAndOpenDetail, bindEvents });

  ctx.renderDetail = {
    syncEditModeUI,
    destroyDetailDuePicker,
    restoreCurrentTaskLocation,
    closeDetail,
    openTaskDetail,
    openTaskDetailByCode,
    updateDetailField,
    openDetailDuePicker,
    renderDetailContent,
    updateEditorStatus,
    enterEditMode,
    exitEditMode,
    saveBody,
    setSidebarTab,
    setSidebarFolded,
    openCommentSidebar,
    jumpToCommentAnchor,
    renderCommentSidebar,
    normalizeDuplicateCommentAnchors,
    refreshCommentSidebarAvailability,
    loadTaskComments,
    checkHashAndOpenDetail,
    bindEvents,
    _test: {
      mergeConcurrentComment: _mergeConcurrentComment,
    },
  };

  return ctx.renderDetail;
}
