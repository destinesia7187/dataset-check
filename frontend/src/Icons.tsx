import type { ReactNode, SVGProps } from 'react';

export type IconName =
  | 'grid'
  | 'upload'
  | 'file'
  | 'check'
  | 'arrow'
  | 'arrow-up-right'
  | 'refresh'
  | 'trash'
  | 'download'
  | 'close'
  | 'database'
  | 'sliders'
  | 'activity'
  | 'folder'
  | 'chevron-right'
  | 'link';

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName;
  size?: number;
}

const paths: Record<IconName, ReactNode> = {
  grid: <><rect x="3.5" y="3.5" width="6" height="6" rx="1"/><rect x="14.5" y="3.5" width="6" height="6" rx="1"/><rect x="3.5" y="14.5" width="6" height="6" rx="1"/><rect x="14.5" y="14.5" width="6" height="6" rx="1"/></>,
  upload: <><path d="M12 15V3.5m-4 4 4-4 4 4"/><path d="M4 14v5.5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V14"/></>,
  file: <><path d="M13.5 3.5H6a1 1 0 0 0-1 1v15a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-11z"/><path d="M13 3.5V9h5.5M8.5 13h7m-7 3.5h5"/></>,
  check: <path d="m5 12 4.5 4.5L19 7"/>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
  'arrow-up-right': <path d="M6 18 18 6M6 6h12v12"/>,
  refresh: <><path d="M19.5 9A8 8 0 1 0 20 14"/><path d="M19.5 3.5V9H14"/></>,
  trash: <><path d="M3.5 6.5h17m-12-3h7m-10 3 1 13a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1l1-13M10 10v7m4-7v7"/></>,
  download: <><path d="M12 3.5V15m-4-4 4 4 4-4"/><path d="M4 15v4.5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V15"/></>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  database: <><ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></>,
  sliders: <><path d="M3 6h3m4 0h11M3 12h11m4 0h3M3 18h5m4 0h9"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/></>,
  activity: <path d="M2.5 12h4l3-8 5 16 3-8h4"/>,
  folder: <path d="M3 19V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/>,
  'chevron-right': <path d="m9 5 7 7-7 7"/>,
  link: <><path d="m10 14 4-4m-5.5 5.5-1 1a3.5 3.5 0 0 1-5-5l4-4a3.5 3.5 0 0 1 5 0m1 1 1-1a3.5 3.5 0 0 1 5 5l-4 4a3.5 3.5 0 0 1-5 0"/></>,
};

export function Icon({ name, size = 16, className = '', ...props }: IconProps) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" className={`icon ${className}`.trim()} {...props}>{paths[name]}</svg>;
}

export function DataCheckMark({ size = 28, className = '', ...props }: Omit<IconProps, 'name'>) {
  return <svg width={size} height={size} viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" className={`brand-mark ${className}`.trim()} {...props}>
    <circle cx="14" cy="14" r="10"/>
    <path d="M14 4V1.5M4 14H1.5M24 14h2.5M14 24v2.5M8.25 10.75l4 6.5 8-8"/>
    <circle cx="8.25" cy="10.75" r="1.5" fill="currentColor" stroke="none"/>
    <circle cx="12.25" cy="17.25" r="1.5" fill="currentColor" stroke="none"/>
    <circle cx="20.25" cy="9.25" r="1.5" fill="currentColor" stroke="none"/>
  </svg>;
}
