// 首屏渲染前确定浅色／深色，避免闪烁。取值与 src/lib/theme.ts 一致：light、dark、system（缺省）。
(function () {
  var pref = 'system';
  try {
    pref = localStorage.getItem('theme') || 'system';
  } catch (e) {}
  var dark =
    pref === 'dark' || (pref === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('dark', dark);
})();
