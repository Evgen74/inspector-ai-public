/** Design tokens (08 §3.4): primary #1F4E8C, radius 4, Golos Text with system fallback, base 14 px. */
import type { ThemeConfig } from 'antd';

export const FONT_FAMILY =
  "'Golos Text', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#1F4E8C',
    borderRadius: 4,
    fontFamily: FONT_FAMILY,
    fontSize: 14,
  },
  components: {
    Layout: { bodyBg: '#f5f7fa', siderBg: '#ffffff', headerBg: '#ffffff' },
  },
};
