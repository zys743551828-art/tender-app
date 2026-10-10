import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Building2,
  ChartNoAxesCombined,
  Check,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  Clock3,
  Command,
  Download,
  FileCheck2,
  FileText,
  Flag,
  FolderOpen,
  Info,
  LayoutDashboard,
  ListChecks,
  LoaderCircle,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Plus,
  ScanText,
  Search,
  Settings,
  Sparkles,
  Sun,
  TriangleAlert,
  Upload,
  Workflow,
  X,
  ZoomIn,
  ZoomOut,
  type LucideProps,
} from 'lucide-react';

/** 界面用到的图标（Lucide）。装饰性使用，aria-hidden；含义总有文字同时表达。 */
const ICONS = {
  Activity,
  ArrowLeft,
  ArrowRight,
  Building2,
  ChartNoAxesCombined,
  Check,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  Clock3,
  Command,
  Download,
  FileCheck2,
  FileText,
  Flag,
  FolderOpen,
  Info,
  LayoutDashboard,
  ListChecks,
  LoaderCircle,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Plus,
  ScanText,
  Search,
  Settings,
  Sparkles,
  Sun,
  TriangleAlert,
  Upload,
  Workflow,
  X,
  ZoomIn,
  ZoomOut,
} as const;

export type IconName = keyof typeof ICONS;

export interface IconProps extends Omit<LucideProps, 'ref'> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 16, strokeWidth = 1.75, ...rest }: IconProps) {
  const C = ICONS[name];
  return <C size={size} strokeWidth={strokeWidth} aria-hidden="true" focusable="false" {...rest} />;
}
