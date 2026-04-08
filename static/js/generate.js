/* generate.js — SSE client for report generation */

(function () {
  const generateBtn = document.getElementById('generate-btn');
  const topicInput  = document.getElementById('topic-input');
  const modelSelect = document.getElementById('model-select');
  if (!generateBtn) return; // page in API-key-required mode

  let currentReport = '';
  let streamingContent = ''; // NEW: accumulated content during stream
  let currentTopic  = '';
  let currentThreadId = null; // NEW: for HITL
  let eventSource   = null;

  const planReviewArea = document.getElementById('plan-review-area');
  const planList = document.getElementById('plan-list');
  const approvePlanBtn = document.getElementById('approve-plan-btn');

  // ── Configure marked ──────────────────────────────────────────
  marked.setOptions({
    breaks: true,
    gfm: true,
  });

  // ── DOM helpers ───────────────────────────────────────────────
  const progressArea = document.getElementById('progress-area');
  const progressBar  = document.getElementById('progress-bar');
  const progressLbl  = document.getElementById('progress-label');
  const statusLog    = document.getElementById('status-log');
  const resultArea   = document.getElementById('result-area');
  const reportOutput = document.getElementById('report-output');
  const inputCard    = document.getElementById('input-card');

  function appendLog(text, bold = false) {
    const p = document.createElement('p');
    p.className = 'log-line' + (bold ? ' bold' : '');
    p.textContent = text;
    statusLog.appendChild(p);
    statusLog.scrollTop = statusLog.scrollHeight;
  }

  function setProgress(value) {
    const pct = Math.round(value * 100);
    progressBar.style.width = pct + '%';
    progressBar.setAttribute('aria-valuenow', pct);
  }

  function showError(message) {
    appendLog('❌ ' + message, true);
    progressLbl.textContent = '오류 발생';
    generateBtn.disabled = false;
    generateBtn.innerHTML = '<i class="bi bi-lightning-charge-fill me-1"></i>다시 시도';
  }

  // ── Start generation ──────────────────────────────────────────
  function startGeneration() {
    currentTopic = topicInput.value.trim();
    if (!currentTopic) {
      topicInput.focus();
      return;
    }

    // Reset UI
    statusLog.innerHTML = '';
    reportOutput.innerHTML = '';
    streamingContent = ''; // NEW
    currentThreadId = null; // RESET
    resultArea.style.display = 'none';
    planReviewArea.style.display = 'none';
    progressArea.style.display = 'block';
    setProgress(0);
    progressLbl.textContent = '연결 중...';
    generateBtn.disabled = true;
    generateBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>생성 중...';

    appendLog('📡 주제: ' + currentTopic, true);
    appendLog('🔄 AI 에이전트를 시작합니다...');

    startSseStream(currentTopic);
  }

  function startSseStream(topic, threadId = null, excluded = null) {
    const selectedModel = modelSelect ? modelSelect.value : 'gpt-5';
    let url = '/generate/stream?topic=' + encodeURIComponent(topic) + '&model_name=' + encodeURIComponent(selectedModel);
    if (threadId) {
        url += '&thread_id=' + encodeURIComponent(threadId);
    }
    if (excluded) {
        url += '&excluded=' + encodeURIComponent(excluded);
    }
    
    if (eventSource) eventSource.close();
    eventSource = new EventSource(url);

    // ── HITL Plan Generated event ─────────────────────────────
    eventSource.addEventListener('plan_generated', (e) => {
        console.log('Event: plan_generated', e.data);
        const data = JSON.parse(e.data);
        currentThreadId = data.thread_id;
        
        // Render sections
        planList.innerHTML = '';
        data.sections.forEach((s, idx) => {
            const item = document.createElement('div');
            item.className = 'list-group-item py-3';
            item.innerHTML = `
                <div class="d-flex w-100 justify-content-between mb-1 align-items-center">
                    <div class="form-check">
                        <input class="form-check-input section-include-cb" type="checkbox" id="include-${idx}" value="${idx}" checked>
                        <label class="form-check-label h6 mb-0 text-dark fw-bold" for="include-${idx}">${idx + 1}. ${s.name}</label>
                    </div>
                    <small class="badge ${s.research ? 'bg-info text-dark' : 'bg-light text-muted'}">
                        ${s.research ? '<i class="bi bi-search me-1"></i>리서치 필요' : '작성만'}
                    </small>
                </div>
                <p class="mb-1 text-muted small ms-4">${s.description || '내용 없음'}</p>
            `;
            planList.appendChild(item);
        });

        // Hide progress momentarily, show plan
        progressArea.style.display = 'none';
        planReviewArea.style.display = 'block';
        planReviewArea.scrollIntoView({ behavior: 'smooth' });
        
        // We close and wait for approval to call again
        eventSource.close();
    });

    // ── Content event (Incremental) ───────────────────────────
    eventSource.addEventListener('content', (e) => {
      console.log('Event: content');
      const data = JSON.parse(e.data);
      if (data.content) {
        // Append new section
        streamingContent += '\n\n' + data.content;
        
        // Show result area early if hidden
        if (resultArea.style.display === 'none') {
            resultArea.style.display = 'block';
        }
        
        // Render current state
        reportOutput.innerHTML = marked.parse(streamingContent);
      }
    });

    // ── Progress event ────────────────────────────────────────
    eventSource.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data);
      console.log('Event: progress', data.step);
      setProgress(data.progress);
      progressLbl.textContent = data.label;
      appendLog(data.label, data.label.includes('---'));
    });

    // ── Complete event ────────────────────────────────────────
    eventSource.addEventListener('complete', (e) => {
      console.log('Event: complete');
      const data = JSON.parse(e.data);
      currentReport = data.report;
      currentTopic  = data.topic || currentTopic;

      setProgress(1);
      progressLbl.textContent = '✅ 완료!';
      appendLog('✅ 보고서 생성 완료!', true);

      // Render final markdown (full replacement to be sure)
      reportOutput.innerHTML = marked.parse(currentReport);

      // Wire download links
      wireDownloads();

      // Show result
      resultArea.style.display = 'block';
      resultArea.scrollIntoView({ behavior: 'smooth', block: 'start' });

      generateBtn.disabled = false;
      generateBtn.innerHTML = '<i class="bi bi-lightning-charge-fill me-1"></i>생성하기';
      eventSource.close();
    });

    // ── Stream Error event (from backend exceptions) ───────────────────
    eventSource.addEventListener('stream_error', (e) => {
      console.warn('Event: stream_error', e);
      try {
        const data = JSON.parse(e.data);
        showError(data.message || '알 수 없는 서버 오류');
      } catch {
        showError('데이터 처리 중 오류가 발생했습니다.');
      }
      eventSource.close();
    });

    // ── Native Error event (Network drops, clean closures) ─────────────
    eventSource.addEventListener('error', (e) => {
      console.warn('Event: native error/close', e);
      
      // If we already errored out, or we are waiting for HITL, or done:
      if (currentThreadId || currentReport || progressLbl.textContent === '오류 발생') {
          console.log('Ignoring native close event (HITL wait or finished)');
          return;
      }
      showError('서버와의 스트림 연결이 끊어졌습니다.');
      eventSource.close();
    });
  }

  // Handle Plan Approval
  approvePlanBtn.addEventListener('click', () => {
    // Gather excluded indices
    const checkboxes = document.querySelectorAll('.section-include-cb');
    const excludedIndices = [];
    checkboxes.forEach(cb => {
        if (!cb.checked) {
            excludedIndices.push(cb.value);
        }
    });

    planReviewArea.style.display = 'none';
    progressArea.style.display = 'block';
    
    if (excludedIndices.length > 0) {
        appendLog(`✅ 리서치 계획이 승인되었습니다. (${excludedIndices.length}개 섹션 제외) 작업을 재개합니다...`, true);
    } else {
        appendLog('✅ 리서치 계획이 승인되었습니다. 작업을 재개합니다...', true);
    }
    
    // Resume stream with the same threadId and excluded sections
    const excludedStr = excludedIndices.length > 0 ? excludedIndices.join(',') : null;
    startSseStream(currentTopic, currentThreadId, excludedStr);
  });

  // ── Wire download links ────────────────────────────────────────
  function wireDownloads() {
    // Markdown download (data URI)
    const mdBlob = new Blob([currentReport], { type: 'text/markdown' });
    const mdUrl  = URL.createObjectURL(mdBlob);
    const btnMd  = document.getElementById('btn-download-md');
    btnMd.href = mdUrl;
    btnMd.download = (currentTopic.replace(/\s+/g, '_') || 'report') + '.md';

    // PDF download — rely on server-side endpoint
    // Encode topic and report content via a hidden form POST to avoid URL length limits
    const btnPdf = document.getElementById('btn-download-pdf');
    // 복수 등록 및 첫 번째 클릭 후 리스너가 제거되는 문제({once: true})를 해결
    const newBtnPdf = btnPdf.cloneNode(true);
    btnPdf.parentNode.replaceChild(newBtnPdf, btnPdf);
    newBtnPdf.addEventListener('click', (e) => {
      e.preventDefault();
      submitPdfForm();
    });
  }

  function submitPdfForm() {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/pdf/generate';
    form.target = '_blank';

    const addField = (name, value) => {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = name;
      input.value = value;
      form.appendChild(input);
    };
    addField('topic', currentTopic);
    addField('content', currentReport);
    document.body.appendChild(form);
    form.submit();
    document.body.removeChild(form);
  }

  // ── Copy button ────────────────────────────────────────────────
  document.getElementById('btn-copy')?.addEventListener('click', async () => {
    if (!currentReport) return;
    try {
      await navigator.clipboard.writeText(currentReport);
      const btn = document.getElementById('btn-copy');
      btn.innerHTML = '<i class="bi bi-check2 me-1"></i>복사됨';
      setTimeout(() => {
        btn.innerHTML = '<i class="bi bi-clipboard me-1"></i>복사';
      }, 2000);
    } catch {
      alert('클립보드 복사에 실패했습니다. 직접 선택하여 복사해 주세요.');
    }
  });

  // ── New report button ──────────────────────────────────────────
  document.getElementById('btn-new')?.addEventListener('click', () => {
    resultArea.style.display = 'none';
    progressArea.style.display = 'none';
    topicInput.value = '';
    topicInput.focus();
    currentReport = '';
    inputCard.scrollIntoView({ behavior: 'smooth' });
  });

  // ── Event listeners ────────────────────────────────────────────
  generateBtn.addEventListener('click', startGeneration);
  topicInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) startGeneration();
  });
})();
