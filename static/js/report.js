/* report.js — actions for the saved report viewer */

(function () {
  // Copy report markdown to clipboard
  const copyBtn = document.getElementById('btn-copy');
  if (copyBtn) {
    copyBtn.addEventListener('click', async () => {
      const raw = window.__reportRaw__;  // injected by template
      if (!raw) return;
      try {
        await navigator.clipboard.writeText(raw);
        copyBtn.innerHTML = '<i class="bi bi-check2 me-1"></i>복사됨';
        setTimeout(() => {
          copyBtn.innerHTML = '<i class="bi bi-clipboard me-1"></i>복사';
        }, 2000);
      } catch {
        alert('클립보드 복사에 실패했습니다. 직접 선택하여 복사해 주세요.');
      }
    });
  }
})();
