/**
 * Design tokens, modelled on the look of the Viseca one app: light grey surfaces,
 * large left-aligned titles, a navy hero card, black pill buttons and blue links.
 * Style only -- no Viseca logos or brand assets.
 */
export const colors = {
  background: "#FAFAFC",
  surface: "#F2F2F7",
  surfaceRaised: "#FFFFFF",
  hero: "#0B2350",
  onHero: "#FFFFFF",
  onHeroMuted: "#B8C4DA",
  text: "#111111",
  textMuted: "#5F6368",
  border: "#D9D9DF",
  primary: "#1C1C1E",
  onPrimary: "#FFFFFF",
  link: "#007AFF",
  success: "#1B7F3B",
  successSurface: "#E3F4E8",
  danger: "#C4152A",
  dangerSurface: "#FDE4E7",
  attention: "#F5A623",
  attentionSurface: "#FFF4DE",
  onAttentionSurface: "#7A4A00",
  scrim: "rgba(0, 0, 0, 0.4)",
} as const;

export const radius = { card: 16, pill: 999, chip: 12, sheet: 24 } as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;

export const type = {
  largeTitle: { fontSize: 34, fontWeight: "500", color: colors.text },
  sectionTitle: { fontSize: 22, fontWeight: "500", color: colors.text },
  amount: { fontSize: 24, fontWeight: "600", color: colors.text },
  body: { fontSize: 18, color: colors.text },
  secondary: { fontSize: 16, color: colors.textMuted },
  small: { fontSize: 15, color: colors.textMuted },
} as const;

/** Swiss formatting: `CHF 1'234.50`. */
export function formatChf(value: number | string): string {
  const number = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(number)) return `CHF ${value}`;
  const [whole, cents] = Math.abs(number).toFixed(2).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  return `${number < 0 ? "-" : ""}CHF ${grouped}.${cents}`;
}
