// Toast notification component.

export function flash(message, tone = 'info') {
  const stack = document.getElementById('flash-stack');
  if (!stack) return;

  const notice = document.createElement('div');
  notice.className = `flash flash-${tone}`;
  notice.textContent = message;
  stack.appendChild(notice);

  setTimeout(() => {
    notice.style.opacity = '0';
    notice.style.transform = 'translateX(10px)';
    setTimeout(() => notice.remove(), 200);
  }, 3200);
}
