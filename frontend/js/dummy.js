document.addEventListener('DOMContentLoaded', () => {
  const grid = document.querySelector('.grid');
  setTimeout(() => grid.classList.add('show'), 60);

  // Tab switching
  const tabs = document.querySelectorAll('.tab');
  tabs.forEach(t => t.addEventListener('click', () => {
    tabs.forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.querySelectorAll('.panel').forEach(p => p.classList.add('hidden'));
    const id = t.getAttribute('data-panel');
    document.getElementById(id).classList.remove('hidden');
  }));

  // Make sure grid fits vertically: adjust auto-rows to evenly distribute
  function fitGrid() {
    const gridEl = document.querySelector('.grid');
    if (!gridEl) return;
    const headerH = document.querySelector('.site-header').offsetHeight || 72;
    const avail = window.innerHeight - headerH - 56; // padding
    const cols = getComputedStyle(gridEl).gridTemplateColumns.split(' ').length;
    const rows = Math.ceil(gridEl.children.length / cols);
    const rowH = Math.floor((avail - (rows - 1) * 20) / rows);
    gridEl.style.gridAutoRows = `${rowH}px`;
  }
  window.addEventListener('resize', fitGrid);
  fitGrid();
});
