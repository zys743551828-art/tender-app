import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** 合并类名：后出现的 Tailwind 工具类覆盖先出现的同类声明。 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
