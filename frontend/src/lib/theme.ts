import { useCallback, useEffect, useState } from 'react';

export type ThemePref = 'light' | 'dark' | 'system';
const KEY = 'theme';

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

function systemDark(): boolean {
  return (
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  );
}

function apply(pref: ThemePref): void {
  document.documentElement.classList.toggle(
    'dark',
    pref === 'dark' || (pref === 'system' && systemDark()),
  );
}

/** 浅色／深色／跟随系统；选择记在本机浏览器里（public/theme.js 在首屏前读取同一个键）。 */
export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(read);
  useEffect(() => {
    apply(pref);
    if (pref !== 'system' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const on = () => {
      apply('system');
    };
    mq.addEventListener('change', on);
    return () => {
      mq.removeEventListener('change', on);
    };
  }, [pref]);
  const set = useCallback((p: ThemePref) => {
    try {
      localStorage.setItem(KEY, p);
    } catch {
      /* 存不下时只在本次会话生效 */
    }
    setPref(p);
  }, []);
  return [pref, set];
}
