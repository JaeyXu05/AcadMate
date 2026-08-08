import { create } from 'zustand';
import * as userApi from '../services/user';

/** 预设主题配置 */
export const PRESET_THEMES = {
  'pure-black': { label: '纯黑', color: '#000000' },
  'deep-blue': { label: '深空蓝', color: '#0a1628' },
  'night-gray': { label: '暗夜灰', color: '#161616' },
  'ink-blue': { label: '墨蓝', color: '#060d17' },
} as const;

export type BgThemeKey = keyof typeof PRESET_THEMES | 'custom';
export type SortType = 'match' | 'staffId' | 'papers';
export type DensityType = 'compact' | 'standard';
export type LanguageType = 'zh' | 'en';

interface SettingsState {
  bgTheme: BgThemeKey;
  bgColor: string;
  defaultSort: SortType;
  cardDensity: DensityType;
  language: LanguageType;
  syncStatus: 'idle' | 'syncing' | 'error';

  setBgTheme: (theme: BgThemeKey, customColor?: string) => void;
  setDefaultSort: (sort: SortType) => void;
  setCardDensity: (density: DensityType) => void;
  setLanguage: (lang: LanguageType) => void;

  /** 从服务端拉取设置并合并到本地 */
  syncFromServer: () => Promise<void>;
  /** 把当前设置同步到服务端 */
  syncToServer: () => Promise<void>;
}

const STORAGE_KEY = 'platform_settings';

function loadSettings(): Partial<SettingsState> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return {};
}

function saveSettings(state: Pick<SettingsState, 'bgTheme' | 'bgColor' | 'defaultSort' | 'cardDensity' | 'language'>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      bgTheme: state.bgTheme,
      bgColor: state.bgColor,
      defaultSort: state.defaultSort,
      cardDensity: state.cardDensity,
      language: state.language,
    }));
  } catch { /* ignore */ }
}

const saved = loadSettings();

export const useSettingsStore = create<SettingsState>((set, get) => ({
  bgTheme: (saved.bgTheme as BgThemeKey) || 'pure-black',
  bgColor: saved.bgColor || PRESET_THEMES['pure-black'].color,
  defaultSort: (saved.defaultSort as SortType) || 'match',
  cardDensity: (saved.cardDensity as DensityType) || 'standard',
  language: (saved.language as LanguageType) || 'zh',
  syncStatus: 'idle',

  setBgTheme: (theme, customColor) => {
    let color: string;
    if (theme === 'custom' && customColor) {
      color = customColor;
    } else if (theme in PRESET_THEMES) {
      color = PRESET_THEMES[theme as keyof typeof PRESET_THEMES].color;
    } else {
      color = PRESET_THEMES['pure-black'].color;
    }
    set({ bgTheme: theme, bgColor: color });
    saveSettings({ ...get(), bgTheme: theme, bgColor: color });
    // 异步同步到服务端
    get().syncToServer();
  },

  setDefaultSort: (sort) => {
    set({ defaultSort: sort });
    saveSettings({ ...get(), defaultSort: sort });
    get().syncToServer();
  },

  setCardDensity: (density) => {
    set({ cardDensity: density });
    saveSettings({ ...get(), cardDensity: density });
    get().syncToServer();
  },

  setLanguage: (lang) => {
    set({ language: lang });
    saveSettings({ ...get(), language: lang });
    get().syncToServer();
  },

  /** 登录后从服务端拉取设置合并到本地 */
  syncFromServer: async () => {
    set({ syncStatus: 'syncing' });
    try {
      const server = await userApi.getSettings();
      const merged = {
        bgTheme: (server.bg_theme as BgThemeKey) || get().bgTheme,
        bgColor: server.bg_color || get().bgColor,
        defaultSort: (server.default_sort as SortType) || get().defaultSort,
        cardDensity: (server.card_density as DensityType) || get().cardDensity,
        language: get().language,
      };
      set(merged);
      saveSettings(merged);
      set({ syncStatus: 'idle' });
    } catch {
      // 未登录或网络错误，保持本地设置
      set({ syncStatus: 'error' });
    }
  },

  /** 把当前设置推送到服务端 */
  syncToServer: async () => {
    const state = get();
    set({ syncStatus: 'syncing' });
    try {
      await userApi.updateSettings({
        bg_theme: state.bgTheme,
        bg_color: state.bgColor,
        default_sort: state.defaultSort,
        card_density: state.cardDensity,
      });
      set({ syncStatus: 'idle' });
    } catch {
      // 网络错误不影响本地使用
      set({ syncStatus: 'error' });
    }
  },
}));